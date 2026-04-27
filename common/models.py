from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String)  # admin, researcher, student

class Asset(Base):
    __tablename__ = "assets"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    category = Column(String)
    status = Column(String)  # available, borrowed, maintenance
    location = Column(String)
    description = Column(String)

class DAQConfig(Base):
    __tablename__ = "daq_configs"
    id = Column(Integer, primary_key=True, index=True)
    sensor_name = Column(String)
    sample_rate = Column(Integer)
    unit = Column(String)

class Camera(Base):
    __tablename__ = "cameras"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    url = Column(String)  # rtsp://admin:password@192.168.1.100:554/stream1
    is_active = Column(Integer, default=1)
