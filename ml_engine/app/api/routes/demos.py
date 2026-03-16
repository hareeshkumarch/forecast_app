from fastapi import APIRouter, HTTPException
import os
import sys
import pandas as pd
import numpy as np
from app.core.config import settings
from app.core.logging import logger
from app.utils.converters import to_native

# Ensure ml_engine root is on path (same fix as upload.py)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from preprocessor import auto_detect_columns

router = APIRouter()


def generate_retail_sales():
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=365, freq="D")
    trend = np.linspace(40000, 75000, 365)
    seasonal = 12000 * np.sin(2 * np.pi * np.arange(365) / 365) + 5000 * np.sin(4 * np.pi * np.arange(365) / 365)
    weekly = 3000 * np.sin(2 * np.pi * np.arange(365) / 7)
    noise = np.random.normal(0, 2500, 365)
    sales = trend + seasonal + weekly + noise
    marketing = np.random.uniform(500, 3000, 365)
    temp = 15 + 15 * np.sin(2 * np.pi * (np.arange(365) - 80) / 365) + np.random.normal(0, 3, 365)
    return pd.DataFrame({"date": dates, "sales": np.round(sales, 2), "marketing_spend": np.round(marketing, 2), "temperature": np.round(temp, 1)})

def generate_product_demand():
    np.random.seed(123)
    dates = pd.date_range("2019-01-07", periods=260, freq="W")
    trend = np.linspace(500, 1200, 260)
    seasonal = 200 * np.sin(2 * np.pi * np.arange(260) / 52)
    noise = np.random.normal(0, 80, 260)
    demand = trend + seasonal + noise
    price = 29.99 - 5 * np.sin(2 * np.pi * np.arange(260) / 52) + np.random.normal(0, 1, 260)
    promo = (np.random.random(260) > 0.8).astype(float)
    return pd.DataFrame({"date": dates, "demand": np.round(demand, 0).astype(int), "price": np.round(price, 2), "promotion": promo})

def generate_monthly_revenue():
    np.random.seed(456)
    dates = pd.date_range("2019-01-01", periods=60, freq="MS")
    trend = np.linspace(50000, 160000, 60)
    seasonal = 15000 * np.sin(2 * np.pi * np.arange(60) / 12)
    noise = np.random.normal(0, 5000, 60)
    revenue = trend + seasonal + noise
    customers = (revenue / 50 + np.random.normal(0, 100, 60)).astype(int)
    ad_spend = revenue * 0.08 + np.random.normal(0, 1000, 60)
    return pd.DataFrame({"date": dates, "revenue": np.round(revenue, 2), "customer_count": customers, "ad_spend": np.round(ad_spend, 2)})

DEMO_DATASETS = {
    "retail_sales": {
        "name": "Retail Sales (Daily)",
        "description": "365 days of daily retail sales with marketing spend and temperature",
        "generator": generate_retail_sales,
        "rows": 365, "cols": 4,
    },
    "product_demand": {
        "name": "Product Demand (Weekly)",
        "description": "5 years of weekly product demand with price and promotions",
        "generator": generate_product_demand,
        "rows": 260, "cols": 4,
    },
    "monthly_revenue": {
        "name": "Monthly Revenue",
        "description": "5 years of monthly revenue with customer count and ad spend",
        "generator": generate_monthly_revenue,
        "rows": 60, "cols": 4,
    },
}

@router.get("")
async def list_demos():
    return [{
        "id": k,
        "name": v["name"],
        "description": v["description"],
        "rows": v["rows"],
        "cols": v["cols"],
    } for k, v in DEMO_DATASETS.items()]

@router.get("/{dataset_id}")
async def get_demo(dataset_id: str):
    if dataset_id not in DEMO_DATASETS:
        raise HTTPException(404, "Demo dataset not found")

    info = DEMO_DATASETS[dataset_id]
    df = info["generator"]()
    
    os.makedirs(settings.UPLOAD_DIRECTORY, exist_ok=True)
    filepath = os.path.join(settings.UPLOAD_DIRECTORY, f"demo_{dataset_id}.csv")
    df.to_csv(filepath, index=False)

    detection = auto_detect_columns(df)
    detection["file_id"] = f"demo_{dataset_id}.csv"
    detection["filename"] = filepath
    detection["original_filename"] = f"{info['name']}.csv"
    return to_native(detection)
