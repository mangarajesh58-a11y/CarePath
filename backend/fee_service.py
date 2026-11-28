"""
Q-Arovia Centralized Dynamic Platform Fee, GST & Payment Gateway Fee Service.
Enforces exact Decimal-based monetary arithmetic (never floating point).
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any, Union
from sqlalchemy.orm import Session
import logging

from models import PlatformContact, PlatformFeeConfig

TWOPLACES = Decimal("0.01")
logger = logging.getLogger(__name__)


def to_decimal(val: Any, default: str = "0.00") -> Decimal:
    """Safely converts any input into a Decimal quantized to 2 decimal places."""
    if val is None or val == "":
        return Decimal(default).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    try:
        clean_str = str(val).strip().replace("₹", "").replace(",", "")
        return Decimal(clean_str).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal(default).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


class FeeCalculationResult:
    """Immutable result object representing exact fee calculations."""
    def __init__(
        self,
        hospital_token_fee: Decimal,
        platform_fee: Decimal,
        gst_percentage: Decimal,
        gst_amount: Decimal,
        gateway_fee_percentage: Decimal,
        gateway_fee_gst: Decimal,
        gateway_fee_amount: Decimal,
        total_extra_fee: Decimal,
        final_amount: Decimal,
        fee_configuration_version: int = 1,
        pass_gateway_fee_to_patient: bool = True,
        gateway_fee_basis: str = "hospital_fee",
    ):
        self.hospital_token_fee = hospital_token_fee
        self.platform_fee = platform_fee
        self.gst_percentage = gst_percentage
        self.gst_amount = gst_amount
        self.gateway_fee_percentage = gateway_fee_percentage
        self.gateway_fee_gst = gateway_fee_gst
        self.gateway_fee_amount = gateway_fee_amount
        self.total_extra_fee = total_extra_fee
        self.final_amount = final_amount
        self.fee_configuration_version = fee_configuration_version
        self.pass_gateway_fee_to_patient = pass_gateway_fee_to_patient
        self.gateway_fee_basis = gateway_fee_basis

    def to_dict(self) -> Dict[str, Any]:
        """Returns dictionary with Decimal values for database insertion."""
        return {
            "hospital_token_fee": self.hospital_token_fee,
            "platform_fee": self.platform_fee,
            "gst_percentage": self.gst_percentage,
            "gst_amount": self.gst_amount,
            "gateway_fee_percentage": self.gateway_fee_percentage,
            "gateway_fee_gst": self.gateway_fee_gst,
            "gateway_fee_amount": self.gateway_fee_amount,
            "total_extra_fee": self.total_extra_fee,
            "final_amount": self.final_amount,
            "fee_configuration_version": self.fee_configuration_version,
            "pass_gateway_fee_to_patient": self.pass_gateway_fee_to_patient,
            "gateway_fee_basis": self.gateway_fee_basis,
        }

    def to_api_dict(self) -> Dict[str, Any]:
        """Returns dictionary formatted for JSON serialization to frontend/clients."""
        return {
            "hospital_token_fee": float(self.hospital_token_fee),
            "platform_fee": float(self.platform_fee),
            "gst_percentage": float(self.gst_percentage),
            "gst_amount": float(self.gst_amount),
            "gateway_fee_percentage": float(self.gateway_fee_percentage),
            "gateway_fee_gst": float(self.gateway_fee_gst),
            "gateway_fee_amount": float(self.gateway_fee_amount),
            "total_extra_fee": float(self.total_extra_fee),
            "final_amount": float(self.final_amount),
            "fee_configuration_version": self.fee_configuration_version,
            "pass_gateway_fee_to_patient": self.pass_gateway_fee_to_patient,
            "gateway_fee_basis": self.gateway_fee_basis,
            # Formatted string representations for clear UI display
            "formatted": {
                "hospital_token_fee": f"₹{self.hospital_token_fee:.2f}",
                "platform_fee": f"₹{self.platform_fee:.2f}",
                "gst_percentage": f"{self.gst_percentage:.1f}%",
                "gst_amount": f"₹{self.gst_amount:.2f}",
                "gateway_fee_percentage": f"{self.gateway_fee_percentage:.1f}%",
                "gateway_fee_gst": f"{self.gateway_fee_gst:.1f}%",
                "gateway_fee_amount": f"₹{self.gateway_fee_amount:.2f}",
                "total_extra_fee": f"₹{self.total_extra_fee:.2f}",
                "final_amount": f"₹{self.final_amount:.2f}",
            }
        }


def get_active_fee_config(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Retrieves the currently active fee configuration from the database.
    Checks PlatformFeeConfig first, then PlatformContact, falling back to system defaults.
    """
    config = {
        "platform_fee": Decimal("10.00"),
        "gst_percentage": Decimal("18.00"),
        "gateway_fee_percentage": Decimal("2.00"),
        "gateway_fee_gst": Decimal("18.00"),
        "gateway_fee_basis": "hospital_fee",
        "pass_gateway_fee_to_patient": True,
        "version": 1,
    }

    if db is None:
        return config

    try:
        # Check active PlatformFeeConfig
        pfc = (
            db.query(PlatformFeeConfig)
            .filter(PlatformFeeConfig.is_active == True)
            .order_by(PlatformFeeConfig.version.desc())
            .first()
        )
        if pfc:
            config["platform_fee"] = to_decimal(pfc.platform_fee, "10.00")
            config["gst_percentage"] = to_decimal(pfc.gst_percentage, "18.00")
            config["gateway_fee_percentage"] = to_decimal(pfc.gateway_fee_percentage, "2.00")
            config["gateway_fee_gst"] = to_decimal(pfc.gateway_fee_gst, "18.00")
            config["gateway_fee_basis"] = str(pfc.gateway_fee_basis or "hospital_fee")
            config["pass_gateway_fee_to_patient"] = bool(pfc.pass_gateway_fee_to_patient)
            config["version"] = int(pfc.version or 1)
            return config

        # Fallback to PlatformContact
        contact = db.query(PlatformContact).first()
        if contact:
            if getattr(contact, "platform_fee", None) is not None:
                config["platform_fee"] = to_decimal(contact.platform_fee, "10.00")
            if getattr(contact, "gst_percentage", None) is not None:
                config["gst_percentage"] = to_decimal(contact.gst_percentage, "18.00")
            if getattr(contact, "gateway_fee_percentage", None) is not None:
                config["gateway_fee_percentage"] = to_decimal(contact.gateway_fee_percentage, "2.00")
            if getattr(contact, "gateway_fee_gst", None) is not None:
                config["gateway_fee_gst"] = to_decimal(contact.gateway_fee_gst, "18.00")
            if getattr(contact, "gateway_fee_basis", None) is not None:
                config["gateway_fee_basis"] = str(contact.gateway_fee_basis)
            if getattr(contact, "pass_gateway_fee_to_patient", None) is not None:
                config["pass_gateway_fee_to_patient"] = bool(contact.pass_gateway_fee_to_patient)
            if getattr(contact, "fee_configuration_version", None) is not None:
                config["version"] = int(contact.fee_configuration_version)
    except Exception as exc:
        logger.warning("Error fetching fee config from DB, using defaults: %s", exc)

    return config


def calculate_dynamic_fees(
    hospital_fee: Union[Decimal, float, int, str],
    fee_config: Optional[Dict[str, Any]] = None,
    db: Optional[Session] = None,
) -> FeeCalculationResult:
    """
    Computes exact dynamic fee breakdown using server-controlled configurations
    and Decimal arithmetic rounded to 2 decimal places (ROUND_HALF_UP).

    Formulas:
    A. Platform Fee = Configured amount
    B. GST on Platform Fee = Platform Fee * GST% / 100
    C. Gateway Fee = (Basis * Gateway Fee %) * (1 + Gateway Fee GST%)
       - where Basis is hospital_fee (default) or subtotal (hospital_fee + platform_fee + gst_amount)
    D. Total Extra Fee = Platform Fee + GST on Platform Fee + Gateway Fee
    E. Final Patient Payment = Hospital Token Fee + Total Extra Fee
    """
    if fee_config is None:
        fee_config = get_active_fee_config(db)

    h_fee = to_decimal(hospital_fee, "0.00")
    p_fee = to_decimal(fee_config.get("platform_fee"), "10.00")
    gst_pct = to_decimal(fee_config.get("gst_percentage"), "18.00")
    gw_pct = to_decimal(fee_config.get("gateway_fee_percentage"), "2.00")
    gw_gst_pct = to_decimal(fee_config.get("gateway_fee_gst"), "18.00")
    gw_basis = str(fee_config.get("gateway_fee_basis", "hospital_fee")).strip().lower()
    pass_gw = bool(fee_config.get("pass_gateway_fee_to_patient", True))
    version = int(fee_config.get("version", 1))

    # A. Platform Fee
    # If hospital fee is zero and it's an emergency/free walk-in, platform fee could be configured
    # but for standard calculations p_fee is preserved
    platform_fee = p_fee

    # B. GST on Platform Fee
    gst_amount = (platform_fee * gst_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    # C. Payment Gateway Fee (Cashfree pricing agreement formula)
    # Gateway Fee = (Transaction Amount * Rate%) * (1 + GST%)
    if pass_gw and (h_fee > 0 or platform_fee > 0):
        if gw_basis == "subtotal":
            gw_transaction_base = (h_fee + platform_fee + gst_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        else:
            # Default 'hospital_fee' basis matching exact spec sample table:
            # ₹100 * 2% = ₹2.00; ₹2.00 * 18% GST = ₹0.36 -> ₹2.36 total
            gw_transaction_base = h_fee if h_fee > 0 else platform_fee

        gw_base_fee = (gw_transaction_base * gw_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        gw_gst_amount = (gw_base_fee * gw_gst_pct / Decimal("100")).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        gateway_fee_amount = (gw_base_fee + gw_gst_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    else:
        gateway_fee_amount = Decimal("0.00")

    # D. Total Extra Fee
    total_extra_fee = (platform_fee + gst_amount + gateway_fee_amount).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    # E. Final Patient Payment
    final_amount = (h_fee + total_extra_fee).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    return FeeCalculationResult(
        hospital_token_fee=h_fee,
        platform_fee=platform_fee,
        gst_percentage=gst_pct,
        gst_amount=gst_amount,
        gateway_fee_percentage=gw_pct,
        gateway_fee_gst=gw_gst_pct,
        gateway_fee_amount=gateway_fee_amount,
        total_extra_fee=total_extra_fee,
        final_amount=final_amount,
        fee_configuration_version=version,
        pass_gateway_fee_to_patient=pass_gw,
        gateway_fee_basis=gw_basis,
    )
