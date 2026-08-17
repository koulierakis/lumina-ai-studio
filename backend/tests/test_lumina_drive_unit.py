from lumina_drive import DriveEvaluationRequest, DriveHazard, DrivePosition, evaluate_drive, haversine_m


def test_haversine_distance_is_reasonable() -> None:
    distance = haversine_m(39.555, 21.768, 39.556, 21.768)
    assert 100 <= distance <= 120


def test_speed_limit_overspeed_alert_gets_high_priority() -> None:
    request = DriveEvaluationRequest(
        position=DrivePosition(latitude=39.555, longitude=21.768, speed_kph=83, heading_deg=0),
        hazards=[DriveHazard(id="limit", kind="speed_limit", latitude=39.560, longitude=21.768, speed_limit_kph=50)],
        warning_distance_m=1000,
    )
    alerts = evaluate_drive(request)
    assert alerts
    assert alerts[0].priority == 100
    assert "50 km/h" in alerts[0].message


def test_hazard_behind_vehicle_is_filtered_when_heading_known() -> None:
    request = DriveEvaluationRequest(
        position=DrivePosition(latitude=39.555, longitude=21.768, speed_kph=50, heading_deg=0),
        hazards=[DriveHazard(id="behind", kind="fixed_camera", latitude=39.550, longitude=21.768)],
        warning_distance_m=1000,
    )
    assert evaluate_drive(request) == []


def test_fixed_camera_is_informational_not_evasion_instruction() -> None:
    request = DriveEvaluationRequest(
        position=DrivePosition(latitude=39.555, longitude=21.768, speed_kph=50),
        hazards=[DriveHazard(id="camera", kind="fixed_camera", latitude=39.556, longitude=21.768)],
    )
    alert = evaluate_drive(request)[0]
    assert "εντός ορίου" in alert.message
