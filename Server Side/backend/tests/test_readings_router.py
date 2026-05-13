import inspect

from app.routers.readings import get_daily


def test_daily_endpoint_accepts_date_range_params():
    sig = inspect.signature(get_daily)

    assert "start_date" in sig.parameters, "start_date param missing from get_daily"
    assert "end_date" in sig.parameters, "end_date param missing from get_daily"


def test_daily_endpoint_days_param_is_optional():
    sig = inspect.signature(get_daily)
    days_param = sig.parameters.get("days")

    assert days_param is not None
    assert days_param.default is not inspect.Parameter.empty, "days must have a default value"
