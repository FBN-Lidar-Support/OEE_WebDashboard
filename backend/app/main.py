from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from query_downtime import get_downtime_yesterday, get_downtime_history_by_machine
from query_yield import get_yield_yesterday
from oee_cal import calculate_oee

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/")
def root():
    return {
        "status": "running"
    }
@app.get("/api/oee/daily/latest")
def get_daily_latest():
    downtime_data, production_date = get_downtime_yesterday()
    yield_data = get_yield_yesterday()
    result = calculate_oee(
        downtime_data,
        yield_data
    )
    return {
        "production_date": str(production_date),
        "machines": result
    }
@app.get("/api/downtime/history/{machine_name}")
def get_downtime_history(machine_name: str, production_date: str):
    target_date = datetime.strptime(
        production_date,
        "%Y-%m-%d"
    ).date()
    history = get_downtime_history_by_machine(
        machine_name=machine_name,
        production_date=target_date
    )
    return {
        "machine": machine_name,
        "production_date": production_date,
        "history": history
    }