from geoalchemy2 import Geometry
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.types import String as SAString, TypeDecorator
from app.core.database import Base


class PostGISPoint(TypeDecorator):
    """
    Tipo di dato ibrido per le coordinate geospaziali (WGS84 EPSG:4326):
    - Su PostgreSQL: mappa direttamente sul tipo nativo PostGIS 'Geometry(POINT, 4326)'
      con creazione automatica dell'indice spaziale GIST e supporto a ST_DWithin / ST_Distance.
    - Su SQLite (sviluppo locale e test unitari): mappa su String/Text trasparente,
      garantendo interoperabilità immediata senza dipendenze C esterne (SpatiaLite).
    """
    impl = Geometry
    cache_ok = True

    def __init__(self, srid: int = 4326, **kwargs):
        super().__init__()
        self.srid = srid
        self.kwargs = kwargs

    def load_dialect_impl(self, dialect):
        if dialect is not None and dialect.name == "postgresql":
            return dialect.type_descriptor(
                Geometry(geometry_type="POINT", srid=self.srid, spatial_index=True, **self.kwargs)
            )
        return dialect.type_descriptor(SAString) if dialect is not None else SAString()


class Regione(Base):
    __tablename__ = "regioni"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nome = Column(String(100), nullable=False, unique=True, index=True)
    codice_istat = Column(String(5), nullable=False, unique=True, index=True)

    # Relazioni
    province = relationship("Provincia", back_populates="regione", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Regione id={self.id} nome='{self.nome}'>"


class Provincia(Base):
    __tablename__ = "province"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nome = Column(String(100), nullable=False, index=True)
    sigla_automobilistica = Column(String(2), nullable=False, index=True)
    regione_id = Column(Integer, ForeignKey("regioni.id", ondelete="CASCADE"), nullable=False)

    # Relazioni
    regione = relationship("Regione", back_populates="province")
    comuni = relationship("Comune", back_populates="provincia", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Provincia id={self.id} sigla='{self.sigla_automobilistica}' nome='{self.nome}'>"


class Comune(Base):
    __tablename__ = "comuni"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nome = Column(String(150), nullable=False, index=True)
    codice_istat = Column(String(6), nullable=True, index=True)
    cap = Column(String(5), nullable=False, index=True)
    provincia_id = Column(Integer, ForeignKey("province.id", ondelete="CASCADE"), nullable=False)

    # Coordinate piane / sferiche (WGS84 EPSG:4326)
    latitudine = Column(Float, nullable=False)
    longitudine = Column(Float, nullable=False)

    # Colonna geometrica PostGIS per indici GIST e query spaziali native (ST_DWithin, ST_Distance)
    coordinate = Column(PostGISPoint(srid=4326), nullable=True)

    # Relazioni
    provincia = relationship("Provincia", back_populates="comuni")
    annunci = relationship("Annuncio", back_populates="comune")

    def __repr__(self) -> str:
        return f"<Comune id={self.id} nome='{self.nome}' cap='{self.cap}'>"
