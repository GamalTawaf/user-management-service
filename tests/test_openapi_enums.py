from app.main import app
from app.prior_auth.schemas import ProcedureDecisionIn


def _schema_prop(openapi: dict, model: str, field: str) -> dict:
    schemas = openapi["components"]["schemas"]
    prop = schemas[model]["properties"][field]
    if "$ref" in prop:
        ref_name = prop["$ref"].rsplit("/", 1)[-1]
        return schemas[ref_name]
    if "allOf" in prop and len(prop["allOf"]) == 1 and "$ref" in prop["allOf"][0]:
        ref_name = prop["allOf"][0]["$ref"].rsplit("/", 1)[-1]
        return schemas[ref_name]
    return prop


def test_openapi_exposes_decision_and_status_enums():
    openapi = app.openapi()

    status = _schema_prop(openapi, "PriorAuthOut", "status")
    assert status.get("type") == "string"
    assert set(status["enum"]) == {"submitted", "in_review", "decided"}

    member_status = _schema_prop(openapi, "MemberPriorAuthOut", "status")
    assert set(member_status["enum"]) == {"submitted", "in_review", "decided"}

    procedure_decision = _schema_prop(openapi, "ProcedureOut", "decision")
    assert set(procedure_decision["enum"]) == {"pending", "approved", "denied"}

    decision_in = _schema_prop(openapi, "ProcedureDecisionIn", "decision")
    assert decision_in.get("type") == "string"
    assert set(decision_in["enum"]) == {"approved", "denied"}


def test_procedure_decision_in_still_accepts_unknown_for_service_error_code():
    # Schema documents approved/denied in OpenAPI but leaves runtime as str so
    # decide.py can still emit invalid_decision for unexpected values.
    outcome = ProcedureDecisionIn(
        procedure_id="00000000-0000-0000-0000-000000000001",
        decision="maybe",
    )
    assert outcome.decision == "maybe"
