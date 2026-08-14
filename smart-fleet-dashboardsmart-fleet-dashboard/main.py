from __future__ import annotations

import hashlib
import math
import os
import random
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
    or_,
)
from sqlalchemy.orm import Session, declarative_base, joinedload, relationship, sessionmaker


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR, 'fleet.db')}",
)

connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# -----------------------------
# Models
# -----------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, default="manager", nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    license_plate = Column(String, unique=True, index=True, nullable=False)
    vehicle_type = Column(String, default="truck", nullable=False)
    capacity_kg = Column(Float, default=1000.0, nullable=False)
    status = Column(String, default="available", nullable=False, index=True)
    lat = Column(Float, default=0.0, nullable=False)
    lng = Column(Float, default=0.0, nullable=False)
    speed_kmh = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    shipments = relationship("Shipment", back_populates="vehicle")


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)
    tracking_code = Column(String, unique=True, index=True, nullable=False)
    customer = Column(String, nullable=False)
    origin_name = Column(String, nullable=False)
    origin_lat = Column(Float, nullable=False)
    origin_lng = Column(Float, nullable=False)
    dest_name = Column(String, nullable=False)
    dest_lat = Column(Float, nullable=False)
    dest_lng = Column(Float, nullable=False)
    priority = Column(String, default="normal", nullable=False)
    weight_kg = Column(Float, default=0.0, nullable=False)
    status = Column(String, default="pending", nullable=False, index=True)
    assigned_vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)

    distance_km = Column(Float, default=0.0, nullable=False)
    eta_minutes = Column(Integer, default=0, nullable=False)
    predicted_delay_minutes = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    vehicle = relationship("Vehicle", back_populates="shipments")


# -----------------------------
# Schemas
# -----------------------------

class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    name: Optional[str] = None


class UserOut(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    role: str

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class VehicleCreate(BaseModel):
    name: str = Field(min_length=2)
    license_plate: str
    vehicle_type: str = "truck"
    capacity_kg: float = Field(gt=0, default=1000.0)
    status: str = "available"
    lat: float = Field(default=41.8781, ge=-90, le=90)
    lng: float = Field(default=-87.6298, ge=-180, le=180)
    speed_kmh: float = Field(default=0.0, ge=0)


class VehicleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2)
    license_plate: Optional[str] = None
    vehicle_type: Optional[str] = None
    capacity_kg: Optional[float] = Field(default=None, gt=0)
    status: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    speed_kmh: Optional[float] = Field(default=None, ge=0)


class VehicleOut(BaseModel):
    id: int
    name: str
    license_plate: str
    vehicle_type: str
    capacity_kg: float
    status: str
    lat: float
    lng: float
    speed_kmh: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShipmentCreate(BaseModel):
    tracking_code: Optional[str] = None
    customer: str
    origin_name: str
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lng: float = Field(..., ge=-180, le=180)
    dest_name: str
    dest_lat: float = Field(..., ge=-90, le=90)
    dest_lng: float = Field(..., ge=-180, le=180)
    weight_kg: float = Field(gt=0)
    priority: str = "normal"
    status: str = "pending"
    assigned_vehicle_id: Optional[int] = None


class ShipmentUpdate(BaseModel):
    tracking_code: Optional[str] = None
    customer: Optional[str] = None
    origin_name: Optional[str] = None
    origin_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    origin_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    dest_name: Optional[str] = None
    dest_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    dest_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    weight_kg: Optional[float] = Field(default=None, gt=0)
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_vehicle_id: Optional[int] = None


class ShipmentOut(BaseModel):
    id: int
    tracking_code: str
    customer: str
    origin_name: str
    origin_lat: float
    origin_lng: float
    dest_name: str
    dest_lat: float
    dest_lng: float
    priority: str
    weight_kg: float
    status: str
    assigned_vehicle_id: Optional[int] = None
    distance_km: float
    eta_minutes: int
    predicted_delay_minutes: int
    created_at: datetime
    updated_at: datetime
    vehicle: Optional[VehicleOut] = None

    model_config = ConfigDict(from_attributes=True)


class AssignRequest(BaseModel):
    vehicle_id: Optional[int] = None


class RouteStopOut(BaseModel):
    sequence: int
    action: str
    shipment_id: int
    tracking_code: str
    label: str
    lat: float
    lng: float
    distance_km: float
    cumulative_km: float
    eta_minutes: float


class RoutePlanOut(BaseModel):
    vehicle_id: int
    vehicle_name: str
    stops: List[RouteStopOut]
    total_distance_km: float
    total_duration_minutes: float
    generated_at: datetime


# -----------------------------
# Database dependency
# -----------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------
# Auth helpers
# -----------------------------

SECRET_KEY = os.getenv("JWT_SECRET", "fleet-demo-secret-change-in-prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "720"))

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
    return f"{salt}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000)
        return secrets.compare_digest(derived.hex(), expected)
    except Exception:
        return False


def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# -----------------------------
# Domain helpers
# -----------------------------

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Distance in kilometers between two coordinates.
    """
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def active_load(db: Session, vehicle_id: int, exclude_shipment_id: Optional[int] = None) -> float:
    query = db.query(func.coalesce(func.sum(Shipment.weight_kg), 0.0)).filter(
        Shipment.assigned_vehicle_id == vehicle_id,
        Shipment.status.in_(["assigned", "in_transit"]),
    )

    if exclude_shipment_id is not None:
        query = query.filter(Shipment.id != exclude_shipment_id)

    return float(query.scalar() or 0.0)


def estimate_delay(
    shipment: Shipment,
    vehicle: Optional[Vehicle],
    distance_km: float,
    now: datetime,
) -> int:
    """
    Heuristic delay prediction model.

    Factors:
    - weekday peak-hour congestion
    - distance
    - load factor
    - priority
    - stable shipment-specific factor
    """
    weekday = now.weekday()
    hour = now.hour

    if weekday < 5 and 7 <= hour < 10:
        congestion = 18.0
    elif weekday < 5 and 16 <= hour < 19:
        congestion = 20.0
    elif 10 <= hour < 16:
        congestion = 7.0
    else:
        congestion = 0.0

    load_factor = 0.0
    if vehicle and vehicle.capacity_kg:
        load_factor = min(1.5, float(shipment.weight_kg) / max(float(vehicle.capacity_kg), 1.0)) * 10.0

    stable_noise = sum(ord(ch) for ch in (shipment.tracking_code or shipment.customer or "FLEET")) % 8
    distance_factor = min(30.0, distance_km * 0.25)

    delay = congestion + load_factor + stable_noise + distance_factor

    if (shipment.priority or "").lower() == "high":
        delay = max(0.0, delay - 5.0)

    return int(round(max(0.0, delay)))


def compute_shipment_metrics(db: Session, shipment: Shipment) -> None:
    vehicle = db.get(Vehicle, shipment.assigned_vehicle_id) if shipment.assigned_vehicle_id else None

    try:
        if vehicle and vehicle.lat is not None and vehicle.lng is not None:
            distance = haversine(
                vehicle.lat,
                vehicle.lng,
                shipment.origin_lat,
                shipment.origin_lng,
            ) + haversine(
                shipment.origin_lat,
                shipment.origin_lng,
                shipment.dest_lat,
                shipment.dest_lng,
            )
        else:
            distance = haversine(
                shipment.origin_lat,
                shipment.origin_lng,
                shipment.dest_lat,
                shipment.dest_lng,
            )
    except Exception:
        distance = 0.0

    speed = float(vehicle.speed_kmh) if vehicle and vehicle.speed_kmh else 35.0
    if speed <= 0:
        speed = 35.0

    duration_minutes = (distance / speed) * 60.0
    delay_minutes = estimate_delay(shipment, vehicle, distance, utcnow())

    shipment.distance_km = round(distance, 2)
    shipment.eta_minutes = int(round(duration_minutes + delay_minutes))
    shipment.predicted_delay_minutes = int(delay_minutes)


def build_route_for_vehicle(db: Session, vehicle: Vehicle) -> List[dict]:
    """
    Route optimizer with pickup-before-delivery constraint.

    Algorithm:
    - Active assigned shipments require pickup then delivery.
    - Active in_transit shipments require delivery only.
    - At every step, choose the nearest available stop.
    - Delivery stops become available only after pickup is completed.
    """
    shipments = (
        db.query(Shipment)
        .filter(
            Shipment.assigned_vehicle_id == vehicle.id,
            Shipment.status.in_(["assigned", "in_transit"]),
        )
        .all()
    )

    if not shipments:
        return []

    tasks = []
    completed_pickups = set()

    for shipment in shipments:
        if shipment.status == "assigned":
            tasks.append(
                {
                    "action": "pickup",
                    "shipment": shipment,
                    "lat": shipment.origin_lat,
                    "lng": shipment.origin_lng,
                }
            )
            tasks.append(
                {
                    "action": "delivery",
                    "shipment": shipment,
                    "lat": shipment.dest_lat,
                    "lng": shipment.dest_lng,
                }
            )
        elif shipment.status == "in_transit":
            completed_pickups.add(shipment.id)
            tasks.append(
                {
                    "action": "delivery",
                    "shipment": shipment,
                    "lat": shipment.dest_lat,
                    "lng": shipment.dest_lng,
                }
            )

    current_lat = vehicle.lat or 0.0
    current_lng = vehicle.lng or 0.0

    speed = float(vehicle.speed_kmh) if vehicle.speed_kmh else 35.0
    if speed <= 0:
        speed = 35.0

    stops = []
    cumulative_km = 0.0
    remaining = tasks[:]

    while remaining:
        available = [
            task
            for task in remaining
            if task["action"] == "pickup" or task["shipment"].id in completed_pickups
        ]

        if not available:
            break

        best_task = None
        best_distance = None

        for task in available:
            distance = haversine(current_lat, current_lng, task["lat"], task["lng"])
            if best_distance is None or distance < best_distance:
                best_task = task
                best_distance = distance

        if best_task is None or best_distance is None:
            break

        remaining.remove(best_task)
        cumulative_km += best_distance
        eta_minutes = (cumulative_km / speed) * 60.0

        shipment = best_task["shipment"]
        label = (
            f"Pickup at {shipment.origin_name}"
            if best_task["action"] == "pickup"
            else f"Deliver to {shipment.dest_name}"
        )

        stops.append(
            {
                "sequence": len(stops) + 1,
                "action": best_task["action"],
                "shipment_id": shipment.id,
                "tracking_code": shipment.tracking_code,
                "label": label,
                "lat": best_task["lat"],
                "lng": best_task["lng"],
                "distance_km": round(best_distance, 2),
                "cumulative_km": round(cumulative_km, 2),
                "eta_minutes": round(eta_minutes, 1),
            }
        )

        current_lat = best_task["lat"]
        current_lng = best_task["lng"]

        if best_task["action"] == "pickup":
            completed_pickups.add(shipment.id)

    return stops


def choose_best_vehicle(
    vehicles: List[Vehicle],
    shipment: Shipment,
    remaining_capacity: dict,
) -> Optional[Vehicle]:
    best_vehicle = None
    best_score = None

    for vehicle in vehicles:
        if vehicle.status == "maintenance":
            continue

        if remaining_capacity.get(vehicle.id, 0.0) < float(shipment.weight_kg or 0.0):
            continue

        distance_to_origin = haversine(
            vehicle.lat or 0.0,
            vehicle.lng or 0.0,
            shipment.origin_lat or 0.0,
            shipment.origin_lng or 0.0,
        )

        linehaul_distance = haversine(
            shipment.origin_lat or 0.0,
            shipment.origin_lng or 0.0,
            shipment.dest_lat or 0.0,
            shipment.dest_lng or 0.0,
        )

        score = distance_to_origin + (0.4 * linehaul_distance)

        if best_score is None or score < best_score:
            best_score = score
            best_vehicle = vehicle

    return best_vehicle


# -----------------------------
# Seed data
# -----------------------------

def seed_data(db: Session) -> None:
    if db.query(func.count(User.id)).scalar() == 0:
        db.add(
            User(
                email="admin@example.com",
                name="Fleet Admin",
                role="admin",
                hashed_password=hash_password("Admin123!"),
            )
        )
        db.flush()

    if db.query(func.count(Vehicle.id)).scalar() == 0:
        vehicles = [
            Vehicle(
                name="Truck Alpha",
                license_plate="TRK-001",
                vehicle_type="truck",
                capacity_kg=12000,
                status="available",
                lat=41.8820,
                lng=-87.6350,
                speed_kmh=38,
            ),
            Vehicle(
                name="Van Beta",
                license_plate="VAN-002",
                vehicle_type="van",
                capacity_kg=3500,
                status="en_route",
                lat=41.9000,
                lng=-87.6500,
                speed_kmh=42,
            ),
            Vehicle(
                name="Truck Gamma",
                license_plate="TRK-003",
                vehicle_type="truck",
                capacity_kg=15000,
                status="available",
                lat=41.8500,
                lng=-87.6200,
                speed_kmh=35,
            ),
            Vehicle(
                name="Van Delta",
                license_plate="VAN-004",
                vehicle_type="van",
                capacity_kg=3000,
                status="maintenance",
                lat=41.8700,
                lng=-87.6400,
                speed_kmh=0,
            ),
            Vehicle(
                name="Truck Epsilon",
                license_plate="TRK-005",
                vehicle_type="truck",
                capacity_kg=18000,
                status="available",
                lat=41.8900,
                lng=-87.6000,
                speed_kmh=36,
            ),
        ]
        db.add_all(vehicles)
        db.flush()

    if db.query(func.count(Shipment.id)).scalar() == 0:
        vehicles = db.query(Vehicle).order_by(Vehicle.id).all()

        if len(vehicles) >= 5:
            v1, v2, v3, v4, v5 = vehicles[:5]

            items = [
                Shipment(
                    tracking_code="SHP-1001",
                    customer="Northwind Retail",
                    origin_name="Chicago Warehouse",
                    origin_lat=41.8820,
                    origin_lng=-87.6350,
                    dest_name="Downtown Store",
                    dest_lat=41.8780,
                    dest_lng=-87.6250,
                    weight_kg=750,
                    priority="high",
                    status="pending",
                ),
                Shipment(
                    tracking_code="SHP-1002",
                    customer="Blue Harbor Foods",
                    origin_name="Harbor Cold Storage",
                    origin_lat=41.8900,
                    origin_lng=-87.6150,
                    dest_name="Airport Cargo",
                    dest_lat=41.9800,
                    dest_lng=-87.9000,
                    weight_kg=980,
                    priority="normal",
                    status="pending",
                ),
                Shipment(
                    tracking_code="SHP-1003",
                    customer="Metro Hardware",
                    origin_name="Westside Depot",
                    origin_lat=41.8500,
                    origin_lng=-87.6200,
                    dest_name="Loop Branch",
                    dest_lat=41.8800,
                    dest_lng=-87.6280,
                    weight_kg=1200,
                    priority="normal",
                    status="assigned",
                    assigned_vehicle_id=v1.id,
                ),
                Shipment(
                    tracking_code="SHP-1004",
                    customer="Lakeside Medical",
                    origin_name="Medical Hub",
                    origin_lat=41.9000,
                    origin_lng=-87.6500,
                    dest_name="North Clinic",
                    dest_lat=41.9200,
                    dest_lng=-87.6400,
                    weight_kg=600,
                    priority="high",
                    status="in_transit",
                    assigned_vehicle_id=v2.id,
                ),
                Shipment(
                    tracking_code="SHP-1005",
                    customer="Prairie Books",
                    origin_name="Print Center",
                    origin_lat=41.8600,
                    origin_lng=-87.6100,
                    dest_name="University Store",
                    dest_lat=41.8000,
                    dest_lng=-87.6000,
                    weight_kg=150,
                    priority="low",
                    status="pending",
                ),
                Shipment(
                    tracking_code="SHP-1006",
                    customer="Skyline Electronics",
                    origin_name="Distribution Center",
                    origin_lat=41.8900,
                    origin_lng=-87.6000,
                    dest_name="Tech Mall",
                    dest_lat=41.8850,
                    dest_lng=-87.6500,
                    weight_kg=900,
                    priority="normal",
                    status="delivered",
                    assigned_vehicle_id=v3.id,
                ),
                Shipment(
                    tracking_code="SHP-1007",
                    customer="Green Grocers",
                    origin_name="Farm Collection Point",
                    origin_lat=41.8400,
                    origin_lng=-87.6300,
                    dest_name="City Market",
                    dest_lat=41.8750,
                    dest_lng=-87.6300,
                    weight_kg=1000,
                    priority="high",
                    status="assigned",
                    assigned_vehicle_id=v3.id,
                ),
            ]

            for shipment in items:
                db.add(shipment)
                db.flush()
                compute_shipment_metrics(db, shipment)

            if v1.status == "available":
                v1.status = "en_route"
            v2.status = "en_route"
            if v3.status == "available":
                v3.status = "en_route"

    db.commit()


# -----------------------------
# App startup
# -----------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()

    yield


app = FastAPI(
    title="Smart Fleet Coordination and Logistics Management Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# Auth endpoints
# -----------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        name=payload.name or payload.email.split("@")[0],
        role="manager",
        hashed_password=hash_password(payload.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/auth/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(user.email, user.role)

    return Token(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@app.get("/api/auth/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


# -----------------------------
# Vehicle endpoints
# -----------------------------

@app.get("/api/vehicles", response_model=List[VehicleOut])
def list_vehicles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(Vehicle).order_by(Vehicle.id).all()


@app.post("/api/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    payload: VehicleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(Vehicle).filter(Vehicle.license_plate == payload.license_plate).first()
    if existing:
        raise HTTPException(status_code=400, detail="License plate already exists")

    vehicle = Vehicle(**payload.model_dump())
    vehicle.updated_at = utcnow()

    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@app.patch("/api/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    data = payload.model_dump(exclude_unset=True)

    if "license_plate" in data and not data["license_plate"]:
        data.pop("license_plate")

    if "license_plate" in data:
        existing = (
            db.query(Vehicle)
            .filter(Vehicle.license_plate == data["license_plate"], Vehicle.id != vehicle_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="License plate already exists")

    for field, value in data.items():
        setattr(vehicle, field, value)

    vehicle.updated_at = utcnow()

    db.commit()
    db.refresh(vehicle)
    return vehicle


@app.delete("/api/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    active_shipments = (
        db.query(Shipment)
        .filter(
            Shipment.assigned_vehicle_id == vehicle_id,
            Shipment.status.in_(["assigned", "in_transit"]),
        )
        .count()
    )

    if active_shipments:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete vehicle with active shipments",
        )

    db.delete(vehicle)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------
# Shipment endpoints
# -----------------------------

@app.get("/api/shipments", response_model=List[ShipmentOut])
def list_shipments(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Shipment).options(joinedload(Shipment.vehicle))

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if q:
        query = query.filter(
            or_(
                Shipment.tracking_code.ilike(f"%{q}%"),
                Shipment.customer.ilike(f"%{q}%"),
            )
        )

    return query.order_by(Shipment.id.desc()).all()


@app.post("/api/shipments", response_model=ShipmentOut, status_code=status.HTTP_201_CREATED)
def create_shipment(
    payload: ShipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = payload.model_dump()

    if not data.get("tracking_code"):
        data["tracking_code"] = f"SHP-{utcnow().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
    else:
        existing = db.query(Shipment).filter(Shipment.tracking_code == data["tracking_code"]).first()
        if existing:
            raise HTTPException(status_code=400, detail="Tracking code already exists")

    shipment = Shipment(**data)

    if not shipment.status:
        shipment.status = "pending"

    if shipment.assigned_vehicle_id:
        vehicle = db.get(Vehicle, shipment.assigned_vehicle_id)
        if not vehicle:
            raise HTTPException(status_code=400, detail="Assigned vehicle does not exist")

        if shipment.status == "pending":
            shipment.status = "assigned"

        if shipment.status in ["assigned", "in_transit"]:
            vehicle.status = "en_route"

    shipment.created_at = utcnow()
    shipment.updated_at = utcnow()

    db.add(shipment)
    db.flush()

    compute_shipment_metrics(db, shipment)

    db.commit()
    db.refresh(shipment)
    return shipment


@app.patch("/api/shipments/{shipment_id}", response_model=ShipmentOut)
def update_shipment(
    shipment_id: int,
    payload: ShipmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    data = payload.model_dump(exclude_unset=True)

    if "tracking_code" in data and not data["tracking_code"]:
        data.pop("tracking_code")

    if "tracking_code" in data:
        existing = (
            db.query(Shipment)
            .filter(
                Shipment.tracking_code == data["tracking_code"],
                Shipment.id != shipment_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Tracking code already exists")

    for field, value in data.items():
        setattr(shipment, field, value)

    if shipment.assigned_vehicle_id is None and shipment.status in ["assigned", "in_transit"]:
        shipment.status = "pending"

    if shipment.status == "pending" and shipment.assigned_vehicle_id:
        shipment.status = "assigned"

    if shipment.assigned_vehicle_id and shipment.status in ["assigned", "in_transit"]:
        vehicle = db.get(Vehicle, shipment.assigned_vehicle_id)
        if vehicle:
            vehicle.status = "en_route"

    shipment.updated_at = utcnow()

    db.flush()
    compute_shipment_metrics(db, shipment)

    db.commit()
    db.refresh(shipment)
    return shipment


@app.post("/api/shipments/{shipment_id}/assign", response_model=ShipmentOut)
def assign_shipment(
    shipment_id: int,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    if shipment.status == "delivered":
        raise HTTPException(status_code=400, detail="Delivered shipments cannot be assigned")

    if payload.vehicle_id:
        vehicle = db.get(Vehicle, payload.vehicle_id)
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found")

        if vehicle.status == "maintenance":
            raise HTTPException(status_code=400, detail="Vehicle is under maintenance")

        load = active_load(db, vehicle.id, exclude_shipment_id=shipment.id)

        if load + float(shipment.weight_kg) > float(vehicle.capacity_kg):
            raise HTTPException(status_code=400, detail="Vehicle capacity exceeded")

        chosen_vehicle = vehicle
    else:
        vehicles = db.query(Vehicle).filter(Vehicle.status.in_(["available", "en_route"])).all()

        remaining_capacity = {
            v.id: max(0.0, float(v.capacity_kg) - active_load(db, v.id, exclude_shipment_id=shipment.id))
            for v in vehicles
        }

        chosen_vehicle = choose_best_vehicle(vehicles, shipment, remaining_capacity)

        if not chosen_vehicle:
            raise HTTPException(status_code=400, detail="No eligible vehicle available")

    shipment.assigned_vehicle_id = chosen_vehicle.id

    if shipment.status == "pending":
        shipment.status = "assigned"

    chosen_vehicle.status = "en_route"
    shipment.updated_at = utcnow()

    db.flush()
    compute_shipment_metrics(db, shipment)

    db.commit()
    db.refresh(shipment)
    return shipment


@app.post("/api/shipments/auto-assign")
def auto_assign_shipments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pending = db.query(Shipment).filter(Shipment.status == "pending").all()

    if not pending:
        return {
            "assigned_count": 0,
            "assignments": [],
        }

    priority_rank = {
        "high": 0,
        "normal": 1,
        "low": 2,
    }

    pending.sort(
        key=lambda item: (
            priority_rank.get((item.priority or "normal").lower(), 3),
            -float(item.weight_kg or 0.0),
        )
    )

    vehicles = db.query(Vehicle).filter(Vehicle.status.in_(["available", "en_route"])).all()

    remaining_capacity = {
        vehicle.id: max(0.0, float(vehicle.capacity_kg) - active_load(db, vehicle.id))
        for vehicle in vehicles
    }

    assignments = []

    for shipment in pending:
        chosen_vehicle = choose_best_vehicle(vehicles, shipment, remaining_capacity)

        if not chosen_vehicle:
            continue

        shipment.assigned_vehicle_id = chosen_vehicle.id
        shipment.status = "assigned"
        chosen_vehicle.status = "en_route"

        remaining_capacity[chosen_vehicle.id] -= float(shipment.weight_kg)

        shipment.updated_at = utcnow()

        db.flush()
        compute_shipment_metrics(db, shipment)

        assignments.append(
            {
                "shipment_id": shipment.id,
                "tracking_code": shipment.tracking_code,
                "vehicle_id": chosen_vehicle.id,
                "vehicle_name": chosen_vehicle.name,
            }
        )

    db.commit()

    return {
        "assigned_count": len(assignments),
        "assignments": assignments,
    }


@app.get("/api/tracking/{tracking_code}", response_model=ShipmentOut)
def track_shipment(
    tracking_code: str,
    db: Session = Depends(get_db),
):
    shipment = (
        db.query(Shipment)
        .options(joinedload(Shipment.vehicle))
        .filter(func.lower(Shipment.tracking_code) == tracking_code.lower())
        .first()
    )

    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    return shipment


# -----------------------------
# Optimization endpoints
# -----------------------------

@app.get("/api/optimization/vehicle/{vehicle_id}", response_model=RoutePlanOut)
def get_optimized_route(
    vehicle_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    stops = build_route_for_vehicle(db, vehicle)

    total_distance_km = round(sum(stop["distance_km"] for stop in stops), 2)
    total_duration_minutes = stops[-1]["eta_minutes"] if stops else 0.0

    return RoutePlanOut(
        vehicle_id=vehicle.id,
        vehicle_name=vehicle.name,
        stops=stops,
        total_distance_km=total_distance_km,
        total_duration_minutes=total_duration_minutes,
        generated_at=utcnow(),
    )


# -----------------------------
# Simulation endpoint
# -----------------------------

@app.post("/api/simulate/gps")
def simulate_gps(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    vehicles = db.query(Vehicle).filter(Vehicle.status.in_(["available", "en_route"])).all()
    moved_vehicle_ids = []

    for vehicle in vehicles:
        if vehicle.status != "en_route":
            vehicle.speed_kmh = 0.0
            vehicle.updated_at = utcnow()
            continue

        stops = build_route_for_vehicle(db, vehicle)

        if not stops:
            vehicle.status = "available"
            vehicle.speed_kmh = 0.0
            vehicle.updated_at = utcnow()
            continue

        next_stop = stops[0]

        current_speed = float(vehicle.speed_kmh or 35.0)
        vehicle.speed_kmh = max(18.0, min(80.0, current_speed + random.uniform(-6.0, 6.0)))

        distance_to_stop = haversine(
            vehicle.lat or 0.0,
            vehicle.lng or 0.0,
            next_stop["lat"],
            next_stop["lng"],
        )

        if distance_to_stop <= 0.05:
            vehicle.lat = next_stop["lat"]
            vehicle.lng = next_stop["lng"]

            shipment = db.get(Shipment, next_stop["shipment_id"])

            if shipment:
                if next_stop["action"] == "pickup" and shipment.status == "assigned":
                    shipment.status = "in_transit"
                    shipment.updated_at = utcnow()
                elif next_stop["action"] == "delivery" and shipment.status in ["assigned", "in_transit"]:
                    shipment.status = "delivered"
                    shipment.updated_at = utcnow()
        else:
            step_km = min(
                distance_to_stop,
                max(0.25, float(vehicle.speed_kmh) * (15.0 / 3600.0)),
            )

            fraction = step_km / distance_to_stop

            vehicle.lat = (vehicle.lat or 0.0) + (next_stop["lat"] - (vehicle.lat or 0.0)) * fraction
            vehicle.lng = (vehicle.lng or 0.0) + (next_stop["lng"] - (vehicle.lng or 0.0)) * fraction

        vehicle.updated_at = utcnow()
        moved_vehicle_ids.append(vehicle.id)

    active_shipments = (
        db.query(Shipment)
        .filter(Shipment.status.in_(["assigned", "in_transit"]))
        .all()
    )

    for shipment in active_shipments:
        compute_shipment_metrics(db, shipment)

    db.commit()

    return {
        "moved_vehicle_ids": moved_vehicle_ids,
        "timestamp": utcnow(),
    }


# -----------------------------
# Dashboard endpoint
# -----------------------------

@app.get("/api/dashboard/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    active_shipments_for_prediction = (
        db.query(Shipment)
        .filter(Shipment.status.in_(["pending", "assigned", "in_transit"]))
        .all()
    )

    for shipment in active_shipments_for_prediction:
        compute_shipment_metrics(db, shipment)

    db.commit()

    vehicle_count = db.query(func.count(Vehicle.id)).scalar()
    shipment_count = db.query(func.count(Shipment.id)).scalar()

    shipment_status_rows = (
        db.query(Shipment.status, func.count(Shipment.id))
        .group_by(Shipment.status)
        .all()
    )

    vehicle_status_rows = (
        db.query(Vehicle.status, func.count(Vehicle.id))
        .group_by(Vehicle.status)
        .all()
    )

    pending_shipments = db.query(func.count(Shipment.id)).filter(Shipment.status == "pending").scalar()

    active_shipments = (
        db.query(func.count(Shipment.id))
        .filter(Shipment.status.in_(["assigned", "in_transit"]))
        .scalar()
    )

    delayed_shipments = (
        db.query(func.count(Shipment.id))
        .filter(
            Shipment.status.in_(["assigned", "in_transit"]),
            Shipment.predicted_delay_minutes > 15,
        )
        .scalar()
    )

    total_capacity = (
        db.query(func.coalesce(func.sum(Vehicle.capacity_kg), 0.0))
        .filter(Vehicle.status.in_(["available", "en_route"]))
        .scalar()
    )

    active_load_value = (
        db.query(func.coalesce(func.sum(Shipment.weight_kg), 0.0))
        .filter(Shipment.status.in_(["assigned", "in_transit"]))
        .scalar()
    )

    fleet_utilization_pct = (
        round(float(active_load_value) / float(total_capacity) * 100.0, 1)
        if total_capacity
        else 0.0
    )

    on_time_total = (
        db.query(func.count(Shipment.id))
        .filter(Shipment.status.in_(["assigned", "in_transit", "delivered"]))
        .scalar()
    )

    on_time = (
        db.query(func.count(Shipment.id))
        .filter(
            Shipment.status.in_(["assigned", "in_transit", "delivered"]),
            Shipment.predicted_delay_minutes <= 10,
        )
        .scalar()
    )

    on_time_rate_pct = round(on_time / on_time_total * 100.0, 1) if on_time_total else 100.0

    alerts = []

    if pending_shipments > 0:
        alerts.append(
            {
                "severity": "warning",
                "message": f"{pending_shipments} shipment(s) are unassigned.",
            }
        )

    if delayed_shipments > 0:
        alerts.append(
            {
                "severity": "critical",
                "message": f"{delayed_shipments} active shipment(s) are predicted to be delayed by more than 15 minutes.",
            }
        )

    maintenance_vehicles = (
        db.query(func.count(Vehicle.id))
        .filter(Vehicle.status == "maintenance")
        .scalar()
    )

    if maintenance_vehicles:
        alerts.append(
            {
                "severity": "info",
                "message": f"{maintenance_vehicles} vehicle(s) are under maintenance.",
            }
        )

    recent_delayed = (
        db.query(Shipment)
        .filter(
            Shipment.status.in_(["assigned", "in_transit"]),
            Shipment.predicted_delay_minutes > 15,
        )
        .order_by(Shipment.predicted_delay_minutes.desc())
        .limit(5)
        .all()
    )

    delayed_list = [
        {
            "tracking_code": item.tracking_code,
            "customer": item.customer,
            "predicted_delay_minutes": item.predicted_delay_minutes,
        }
        for item in recent_delayed
    ]

    return {
        "generated_at": utcnow(),
        "kpis": {
            "vehicles": vehicle_count,
            "shipments": shipment_count,
            "active_shipments": active_shipments,
            "pending_shipments": pending_shipments,
            "delayed_shipments": delayed_shipments,
            "fleet_utilization_pct": fleet_utilization_pct,
            "on_time_rate_pct": on_time_rate_pct,
        },
        "shipments_by_status": {status_value: count for status_value, count in shipment_status_rows},
        "vehicles_by_status": {status_value: count for status_value, count in vehicle_status_rows},
        "alerts": alerts,
        "delayed_shipments": delayed_list,
    }


# -----------------------------
# Static frontend
# -----------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
