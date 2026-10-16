"""
Pydantic schemas: the API's contract and its first line of defence.

Validation here is not ceremony. The model was trained on prices in a bounded range,
non-negative rainfall, and hours 0-23. Feed it a price of -5 or an hour of 99 and it
will not error - it will happily extrapolate and return a confident, wrong number.
A pricing engine that silently returns garbage is worse than one that returns 422.
"""
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class WeatherCondition(str, Enum):
    clear = "Clear"
    cloudy = "Cloudy"
    rainy = "Rainy"
    stormy = "Stormy"


class PredictRequest(BaseModel):
    product_id: str = Field(..., description="e.g. SKU-MINI-CAB")

    # --- time ---
    hour: int = Field(..., ge=0, le=23, description="Hour of day, 0-23")
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday .. 6=Sunday")
    month: int = Field(..., ge=1, le=12)
    is_holiday: bool = False

    # --- weather ---
    temperature: float = Field(..., ge=-30, le=55, description="Celsius")
    precipitation: float = Field(..., ge=0, le=100, description="mm/hour")
    weather_condition: WeatherCondition = WeatherCondition.clear

    # --- competitors --- (prices are in INR; the ceiling is high enough for ₹ scale)
    competitor_1_price: float = Field(..., gt=0, le=1_000_000)
    competitor_2_price: float = Field(..., gt=0, le=1_000_000)
    competitor_3_price: float = Field(..., gt=0, le=1_000_000)

    # --- our position ---
    current_price: Optional[float] = Field(
        None, gt=0, le=1_000_000,
        description="Today's price in INR. Defaults to the product's base price.")
    unit_cost: Optional[float] = Field(
        None, ge=0, le=1_000_000,
        description="Cost of goods in INR. Defaults to the product's known cost.")

    # --- business rules ---
    objective: Literal["profit", "revenue"] = Field(
        "profit",
        description=("Profit is the default and it is not arbitrary. Demand here is "
                     "ELASTIC (|e| > 1), and for elastic demand revenue is proportional "
                     "to P^(1+e), which rises monotonically as price FALLS. So a "
                     "revenue-maximising optimiser recommends the lowest legal price "
                     "for every product, forever. Profit has a cost floor, so it has a "
                     "genuine interior peak."))
    max_change_pct: float = Field(
        30.0, ge=1, le=60,
        description=("Guardrail. The model has never seen a price far outside its "
                     "training range, so do not let it recommend one."))

    @model_validator(mode="after")
    def cost_below_price(self):
        if self.unit_cost is not None and self.current_price is not None:
            if self.unit_cost >= self.current_price:
                raise ValueError(
                    f"unit_cost ({self.unit_cost}) must be below current_price "
                    f"({self.current_price}) - you are already selling at a loss, "
                    f"and no price optimiser can fix that.")
        return self


class CurvePoint(BaseModel):
    price: float
    demand: float
    revenue: float
    profit: float


class PredictResponse(BaseModel):
    product_id: str
    objective: str

    current_price: float
    recommended_price: float
    price_change_pct: float

    current_demand: float
    recommended_demand: float

    current_revenue: float
    recommended_revenue: float
    revenue_lift_pct: float

    current_profit: float
    recommended_profit: float
    profit_lift_pct: float

    elasticity: float
    elasticity_label: str
    unit_cost: float

    guardrail_hit: bool
    warning: Optional[str] = None

    curve: List[CurvePoint]


class ModelMetrics(BaseModel):
    selected_model: str
    rmse: float
    r2: float
    price_elasticity: float
    true_elasticity: float
    elasticity_recovery_error: float
    improvement_vs_baseline_pct: float
    all_models: dict
    feature_importance: List[dict]
    elasticity_by_segment: dict
    elasticity_row_correlation: float
    train_rows: int
    test_rows: int
