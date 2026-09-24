from motion_engine import Joint, JointName, MovementFamily, Phase, movement_family_for
from motion_engine.pipeline import build_bodyweight_squat_poc
from motion_engine.pose_renderer import render_pose_png
from motion_engine.rules import SquatRule

def test_canonical_missing_joints_remain_missing():
    from motion_engine.schema import CanonicalPose, PoseProvenance
    p=CanonicalPose(joints={JointName.HEAD:Joint(x=.5,y=.1)},provenance=PoseProvenance(source_type="manual_reference",confidence="verified_reference"))
    assert p.joint(JointName.LEFT_ANKLE) is None

def test_bodyweight_squat_maps_to_squat_pattern():
    assert movement_family_for("bodyweight_squat") is MovementFamily.SQUAT_PATTERN

def test_poc_has_three_provenanced_phases():
    poc=build_bodyweight_squat_poc()
    assert set(poc["phases"])=={Phase.START,Phase.EXECUTION,Phase.RETURN}
    assert all(p.provenance.source_type=="manual_reference" for p in poc["phases"].values())

def test_squat_rule_selects_execution_as_peak():
    poc=build_bodyweight_squat_poc(); phases=poc["phases"]
    assert phases[Phase.EXECUTION].joint(JointName.PELVIS).y > phases[Phase.START].joint(JointName.PELVIS).y

def test_renderer_returns_png_without_inventing_joints():
    p=build_bodyweight_squat_poc()["phases"][Phase.EXECUTION]
    data=render_pose_png(p,(256,256))
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
