"""
ID checks (KYC) for every driver, and for women riders who turn on Women Raahi.

A demo of the real flow: the person uploads an ID document and a selfie (drivers also their
driving licence and their vehicle's registration certificate, the RC), and an admin checks
them by eye and approves or rejects. Approval sets the account's gender from the document,
so nobody can pick "woman" to get Women Raahi rides. The result goes to the person by email
and SMS, as well as live in the app.

The images are deleted as soon as the review is done: Raahi keeps the result, never a copy
of anyone's ID. A real launch would replace the admin review with DigiLocker or a licensed
KYC provider; the rest of the app would not change.
"""
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

import appdb
import mailer
import sms
from rides import current_user, hub, public_user, require_admin, show_plate

router = APIRouter(prefix="/api", tags=["kyc"])

ID_DOCUMENTS = {"aadhaar": "Aadhaar (masked)", "voter": "Voter ID", "passport": "Passport",
                "licence": "Driving licence"}
DOCUMENT_GENDERS = ("female", "male", "other")
MAX_IMAGE_CHARS = 2_000_000       # about 1.5 MB of image; the app shrinks photos well below this
IMAGE = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/]+=*")
# Indian registration numbers: state, RTO number, series, number (JK02AB1234), or the
# Bharat series used across states (22BH1234AB).
PLATE = re.compile(r"[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}|\d{2}BH\d{4}[A-Z]{1,2}")


def clean_plate(text: str) -> str:
    return re.sub(r"[\s\-.]", "", text or "").upper()


class KycBody(BaseModel):
    document: str
    id_image: str = Field(..., max_length=MAX_IMAGE_CHARS)
    selfie: str = Field(..., max_length=MAX_IMAGE_CHARS)
    licence_image: str | None = Field(None, max_length=MAX_IMAGE_CHARS)
    rc_image: str | None = Field(None, max_length=MAX_IMAGE_CHARS)       # vehicle registration certificate
    plate: str | None = Field(None, max_length=20)
    consent: bool = False


class ReviewBody(BaseModel):
    approve: bool
    gender: str | None = None             # as printed on the document
    note: str = Field("", max_length=300)


def kind_for(user: dict) -> str:
    if user["role"] == "driver":
        return "driver"
    if user["role"] == "rider":
        return "women"
    raise HTTPException(403, "Admin accounts are not verified here.")


def received_message(user: dict, kind: str) -> tuple[str, str]:
    """(subject, body) of the email confirming the documents arrived and are waiting for review."""
    first = user["name"].split()[0]
    if kind == "driver":
        return ("We have received your Raahi driver application",
                f"Hello {first},\n\nThank you for applying to drive with Raahi. We have received your ID, "
                f"driving licence, vehicle RC and selfie, and our team is now reviewing them.\n\n"
                f"Vehicle: {show_plate(user.get('plate')) or 'as registered'}\n\n"
                f"There is nothing more to do for now. We will email you as soon as your application is "
                f"approved, or tell you what to fix if something is missing.\n\nTeam Raahi")
    return ("We have received your ID for Women Raahi",
            f"Hello {first},\n\nThank you for sending your ID for Women Raahi. Our team is now checking it, "
            f"and we will email you as soon as it is done.\n\nTeam Raahi")


@router.post("/kyc")
async def submit(body: KycBody, background: BackgroundTasks, user: dict = Depends(current_user)):
    kind = kind_for(user)
    if user.get("kyc") == "pending":
        raise HTTPException(409, "Your documents are already being checked.")
    if user.get("kyc") == "approved":
        raise HTTPException(409, "You are already verified.")
    if kind == "women" and user.get("gender") != "female":
        raise HTTPException(403, "Women Raahi verification is for women riders.")
    if not body.consent:
        raise HTTPException(422, "Please agree to the ID check to continue.")
    if body.document not in ID_DOCUMENTS:
        raise HTTPException(422, "Choose which ID document you are uploading.")
    if kind == "driver" and not body.licence_image:
        raise HTTPException(422, "Add a photo of your driving licence.")
    if kind == "driver" and not body.rc_image:
        raise HTTPException(422, "Add a photo of your vehicle's RC (registration certificate).")
    licence = body.licence_image if kind == "driver" else None
    rc = body.rc_image if kind == "driver" else None
    plate = None
    if kind == "driver":
        plate = clean_plate(body.plate)
        if not PLATE.fullmatch(plate):
            raise HTTPException(422, "Enter your vehicle's number plate, like JK02 AB 1234.")
        if appdb.plate_in_use(plate, user["id"]):
            raise HTTPException(409, "Another driver has already registered this number plate.")
    for image in (body.id_image, body.selfie, licence, rc):
        if image is not None and not IMAGE.fullmatch(image):
            raise HTTPException(422, "Upload the photos as JPEG, PNG or WebP images.")

    appdb.save_verification(user["id"], kind, body.document, body.id_image, body.selfie, licence, plate, rc)
    for admin_id in list(hub.admins):
        await hub.send(admin_id, {"type": "verification", "name": user["name"], "role": user["role"]})
    updated = appdb.get_user(user["id"])
    background.add_task(mailer.send_quietly, updated.get("email"), *received_message(updated, kind))
    return public_user(updated)


def verification_view(row: dict, with_images: bool) -> dict:
    view = {k: row[k] for k in ("id", "kind", "status", "note", "created_at", "reviewed_at",
                                "name", "phone", "role", "vehicle", "gender")}
    view["document"] = ID_DOCUMENTS.get(row["document"], row["document"])
    view["plate"] = show_plate(row.get("plate"))
    if with_images:
        view.update(id_image=row["id_image"], selfie=row["selfie"], licence_image=row["licence_image"],
                    rc_image=row.get("rc_image"))
    return view


@router.get("/admin/verifications")
def verifications(admin: dict = Depends(require_admin)):
    return {"pending": [verification_view(r, True) for r in appdb.list_verifications("pending")],
            "reviewed": [verification_view(r, False) for r in
                         appdb.list_verifications("approved", 20) + appdb.list_verifications("rejected", 20)]}


def decision_messages(user: dict, kind: str, approved: bool, note: str | None) -> tuple[str, str, str]:
    """(email subject, email body, SMS text) telling the person how their ID check went."""
    first = user["name"].split()[0]
    plate = show_plate(user.get("plate"))
    if kind == "driver" and approved:
        return ("Verification completed: you can now drive with Raahi",
                f"Hello {first},\n\nYour verification is completed. Our team has checked your ID, driving "
                f"licence, vehicle RC and selfie, and your registration as a Raahi driver is approved.\n\n"
                f"Vehicle: {plate or 'as registered'}\n\n"
                f"You can now go online, accept rides and drive with Raahi:\n"
                f"  1. Open the Raahi Driver app and log in.\n"
                f"  2. Set your location and tap Go online.\n"
                f"  3. Accept the ride requests you receive.\n\n"
                f"Welcome aboard,\nTeam Raahi",
                f"Raahi: {first}, your verification is completed. You can now go online, accept rides and "
                f"drive with Raahi.")
    if kind == "driver":
        return ("We could not approve your Raahi driver registration yet",
                f"Hello {first},\n\nWe checked your documents but could not approve your registration as a "
                f"Raahi driver yet.\n\nReason: {note}\n\nPlease open the Raahi Driver app and send your "
                f"documents again.\n\nRaahi",
                f"Raahi: {first}, your driver registration was not approved: {note}. Please send your "
                f"documents again in the app.")
    if approved:
        return ("Women Raahi is ready for you",
                f"Hello {first},\n\nThank you for waiting. We have checked your ID and Women Raahi is now on "
                f"for your account. Your rides in Women Raahi go only to women drivers.\n\nYou can turn it on "
                f"or off any time from the pink Women Raahi button in the Raahi app.\n\nSafe travels,\nRaahi",
                f"Raahi: {first}, your ID is verified and Women Raahi is ready. Your rides in this mode go only "
                f"to women drivers.")
    return ("We could not verify your ID for Women Raahi",
            f"Hello {first},\n\nWe checked the ID you sent for Women Raahi but could not verify it.\n\n"
            f"Reason: {note}\n\nPlease tap the Women Raahi button in the Raahi app and send it again.\n\nRaahi",
            f"Raahi: {first}, we could not verify your ID for Women Raahi: {note}. Please send it again in "
            f"the app.")


def notify_decision(user: dict, kind: str, approved: bool, note: str | None):
    """Runs after the response: a slow or failing mail or SMS service never blocks the admin."""
    subject, body, text = decision_messages(user, kind, approved, note)
    mailer.send_quietly(user.get("email"), subject, body)     # a failure is logged; the result is still in the app
    try:
        sms.send(user["phone"], text)
    except sms.SmsError:
        pass


@router.post("/admin/verifications/{verification_id}")
async def review(verification_id: int, body: ReviewBody, background: BackgroundTasks,
                 admin: dict = Depends(require_admin)):
    found = appdb.get_verification(verification_id)
    if found is None:
        raise HTTPException(404, "Verification not found.")
    note = body.note.strip()
    if body.approve:
        if body.gender not in DOCUMENT_GENDERS:
            raise HTTPException(422, "Choose the gender printed on the document.")
        if found["kind"] == "women" and body.gender != "female":
            raise HTTPException(422, "Women Raahi is only for women. Reject this request instead.")
    elif len(note) < 3:
        raise HTTPException(422, "Say why, so the person knows what to fix.")

    user_id = appdb.review_verification(verification_id, body.approve, body.gender, note or None)
    if user_id is None:
        raise HTTPException(409, "This request has already been reviewed.")
    user = appdb.get_user(user_id)
    await hub.send(user_id, {"type": "kyc", "user": public_user(user)})
    background.add_task(notify_decision, user, found["kind"], body.approve, note or None)
    return public_user(user)
