"""
Esquemas de Datos y Contratos de Comunicación para Agentes ARIA.
Basado en la especificación de 43 campos de 'Campos_prueba' y las Historias de Usuario de los Agentes.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
import json


@dataclass
class AlertInput:
    """Representa el payload de una alerta transaccional recibida por ARIA (43 campos sintéticos)."""
    customerid: str
    eventtype: str
    channel: str
    integrationpoint: str
    amount_value: float
    fecha_transaccion: str
    marcacion_final: Optional[str] = None
    razon_marcacion: Optional[str] = None

    # Risk Scores
    biocatch_score: Optional[float] = None
    Model_score: Optional[float] = None
    
    # Biocatch Signals
    biocatch_isMobileRat: int = 0
    biocatch_isEmulator: int = 0
    biocatch_isRat: int = 0
    biocatch_isBot: int = 0
    biocatch_indrobo1: int = 0
    
    # Customer Metadata / Demographic
    tipo_documento: Optional[str] = None
    numero_documento: Optional[str] = None
    nombre_razon_social: Optional[str] = None
    fecha_nacimiento: Optional[str] = None
    sexo: Optional[str] = None
    fecha_expedicion_documento: Optional[str] = None
    indicador_revinculado: int = 0
    codigo_ciudad: Optional[str] = None
    ciudad: Optional[str] = None
    empleado_banco: int = 0
    # Segmento de cliente (ej. "WEALTH", "PREMIUM_VIP") -- no viene en el dataset
    # sintético actual (43 campos de Campos_prueba), pero el campo queda listo para
    # cuando se integre ARIC/3270 PE55: ver agents/_modus_operandi.evaluar_reglas_duras.
    segmento: Optional[str] = None
    fecha_alta: Optional[str] = None
    direccion: Optional[str] = None
    correo_1: Optional[str] = None
    correo_2: Optional[str] = None
    celular: Optional[str] = None
    fecha_ultima_modificacion: Optional[str] = None
    
    # Historical Max Amounts
    MontoMasAltoPSE: float = 0.0
    MontoMasAltoPasarelaPago: float = 0.0
    MontoMasAltoBreB: float = 0.0
    MontoMasAltoGlomo: float = 0.0
    MontoMasAltoNet: float = 0.0
    MontoMasAltoPrestamo: float = 0.0
    MontoMasAltoRetirosTarjeta: float = 0.0
    
    # Additional Context
    tipo: Optional[str] = None
    transacciones_json: str = "[]"
    fecha_primer_marcacion: Optional[str] = None
    fecha_ultima_marcacion: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AlertInput":
        """Crea una instancia normalizada ignorando campos adicionales o convirtiendo tipos."""
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys and v is not None}
        
        # Conversiones numéricas seguras
        for num_field in ['amount_value', 'biocatch_score', 'Model_score', 
                          'MontoMasAltoPSE', 'MontoMasAltoPasarelaPago', 'MontoMasAltoBreB',
                          'MontoMasAltoGlomo', 'MontoMasAltoNet', 'MontoMasAltoPrestamo',
                          'MontoMasAltoRetirosTarjeta']:
            if num_field in filtered:
                try:
                    filtered[num_field] = float(filtered[num_field])
                except (ValueError, TypeError):
                    filtered[num_field] = 0.0
                    
        for int_field in ['biocatch_isMobileRat', 'biocatch_isEmulator', 'biocatch_isRat', 
                          'biocatch_isBot', 'biocatch_indrobo1', 'indicador_revinculado', 'empleado_banco']:
            if int_field in filtered:
                try:
                    filtered[int_field] = int(float(filtered[int_field]))
                except (ValueError, TypeError):
                    filtered[int_field] = 0

        if 'customerid' in filtered:
            filtered['customerid'] = str(filtered['customerid']).split('.')[0]

        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        # Limpiar transacciones_json para que el LLM lo lea nativo sin barras invertidas (\)
        result["transacciones_json"] = self.get_recent_transactions()
        return result

    def get_recent_transactions(self) -> List[Dict[str, Any]]:
        """Devuelve el array parseado del historial de transacciones recientes."""
        if not self.transacciones_json:
            return []
        try:
            raw = json.loads(self.transacciones_json)
            if isinstance(raw, list):
                result = []
                for item in raw:
                    if isinstance(item, str):
                        try:
                            result.append(json.loads(item))
                        except Exception:
                            pass
                    elif isinstance(item, dict):
                        result.append(item)
                return result
        except Exception:
            pass
        return []

    def is_cold_start(self) -> bool:
        """Determina si el usuario cae en la regla Cold Start (sin historial o recién registrado)."""
        txs = self.get_recent_transactions()
        return len(txs) == 0 or self.fecha_alta is None or self.fecha_alta == ''


@dataclass
class PerfilamientoOutput:
    """Respuesta del Agente de Perfilamiento (HU-2.0.1 a HU-2.0.5).
    Traduce los campos crudos de una alerta a descripciones en lenguaje natural."""
    perfil_usuario: str          # Descripción narrativa del cliente
    perfil_transaccion: str      # Descripción narrativa de la transacción evaluada
    perfil_historico: str        # Resumen narrativo del comportamiento reciente de la cuenta
    hipotesis_sospecha: str      # Deducción del LLM de por qué la alerta podría ser sospechosa
    texto_consolidado: str       # Las 4 descripciones anteriores unidas, listas para el Clasificador
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClasificadorOutput:
    """Respuesta del Agente Clasificador (HU-2.1.2).

    No incluye un campo de confianza: un LLM autoreportando un número de
    "confianza" no calibrado es un dato inventado, no una medición real (ver
    docs/HU-Perfilamiento.md). Si se necesita una señal de confianza en el
    futuro, debe venir de una fuente medible (log-probs, self-consistency,
    calibración contra un set de validación), no de pedírselo al modelo.
    """
    marcacion_aric: str          # RISK | NO_RISK | RISK_SUSPECTED — decisión directa del LLM en el triage rápido
    cot_justificacion: str       # CoT resumido de 1-2 oraciones
    regla_cold_start_aplicada: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalistaOutput:
    """Respuesta del Agente Analista (HU-2.2.1 / HU-2.2.3)."""
    confirmado: bool            # True si confirma la clasificación del Clasificador
    clasificacion_final: str    # Clasificación ratificada o rectificada
    hipotesis_refutadora: str   # Hipótesis analizada
    evidencia: List[str]        # Puntos de evidencia encontrados
    nivel_incertidumbre: str    # BAJO | MEDIO | ALTO
    requiere_escalamiento: bool # True si escala a analista humano
    razon_escalamiento: Optional[str] = None
    iteraciones_realizadas: int = 1
    marcacion_aric: str = ""    # RISK | NO_RISK | RISK_SUSPECTED — derivado determinísticamente, no vía LLM (ver AnalistaAgent)
    modus_operandi: str = ""    # Nombre de MO derivado determinísticamente de clasificacion_final (ver agents/_modus_operandi.py)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EjecutorOutput:
    """Respuesta del Agente Ejecutor (HU-2.3.1 / HU-2.3.2 / HU-2.3.3)."""
    marcacion_aric: str          # RISK | NO_RISK | RISK_SUSPECTED
    disparar_voicebot: bool      # True si se activa flujo VoiceBot
    accion_operativa: str        # Descripción de la acción determinista recomendada
    trazabilidad_id: str
    motivo_voicebot: Optional[str] = None
    acciones_sugeridas: List[str] = field(default_factory=list)  # Bloqueos concretos por MO/taxonomía (ver agents/_modus_operandi.py)
    observacion_aric: str = ""   # Observación estandarizada "[MO: ...] [CANAL: ...] [HABITO: ...] [DISP: ...] - texto"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



@dataclass
class DocumentadorOutput:
    """Respuesta del Agente Documentador (HU-2.4.1 / HU-2.4.2)."""
    reporte_cierre_markdown: str # Documento de cierre estructurado
    es_nueva_variante: bool      # True si detecta patrón de nueva variante
    notificar_senior: bool       # True si envía alerta a Analista Senior
    resumen_ejecutivo: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
