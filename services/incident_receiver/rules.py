"""Explicit, inspectable correlation and demonstration runbook policy."""
from dataclasses import dataclass
import hashlib

SEVERITIES = ('INFO', 'WARNING', 'HIGH', 'CRITICAL')
STATUSES = ('FIRING', 'ACKNOWLEDGED', 'INVESTIGATING', 'MITIGATED', 'RESOLVED')
JAM_ALERTS = {'ProductionLineBlocked','ComputerVisionAnomaly','ExcessiveVibration',
              'QualityDegradation','MLAnomaly'}


@dataclass(frozen=True)
class Rule:
    title: str
    severity: str
    cause: str
    steps: tuple[str, ...]


RULES = {
 'PRODUCTION_JAM': Rule('Production Line Jam','HIGH',
   'A production blocked-sensor alert indicates conveyor obstruction; inspect correlated evidence to confirm the cause.',
   ('Verify conveyor obstruction and the approved line safety state.',
    'Follow local isolation procedures before approaching equipment.',
    'Remove the blocking object only when authorized and safe.',
    'Verify the blocked sensor and conveyor speed recovery.',
    'Confirm quality score and normal process signals before restarting.')),
 'MOTOR_OVERHEAT': Rule('Motor Overheating','HIGH',
   'The motor temperature threshold was exceeded; load or cooling may contribute.',
   ('Verify the temperature sensor reading.', 'Inspect motor load and ventilation/cooling.',
    'Reduce or stop equipment according to approved procedures.', 'Confirm the temperature returns to its normal range.')),
 'EXCESSIVE_VIBRATION': Rule('Excessive Motor Vibration','HIGH',
   'A vibration threshold was exceeded; mechanical load, alignment or obstruction requires inspection.',
   ('Verify the vibration reading.', 'Inspect load, mounting and alignment using approved procedures.',
    'Check for a conveyor obstruction.', 'Confirm vibration returns to the normal envelope.')),
 'QUALITY_DEGRADATION': Rule('Production Quality Degradation','WARNING',
   'The PLC quality score fell below the configured threshold.',
   ('Verify the reported quality score.', 'Inspect product flow and process settings.',
    'Check for related speed, vibration or obstruction signals.', 'Confirm quality recovers before releasing production.')),
 'CAMERA_DEGRADATION': Rule('Camera Image Degradation','WARNING',
   'Classical image analysis reported darkness, blur, obstruction or a red visual anomaly; consult the recorded reasons.',
   ('Inspect the raw and annotated camera feeds.', 'Check lighting, focus and lens obstruction.',
    'Compare brightness, blur and obstruction measurements.', 'Confirm normal image statistics recover.')),
 'CAMERA_OUTAGE': Rule('Camera Stream Unavailable','HIGH',
   'A camera, publisher or video-path availability signal is failing.',
   ('Check camera and MediaMTX service health.', 'Check publisher logs and RTSP connectivity.',
    'Verify the camera OT network path.', 'Confirm raw RTSP/HLS frames and CV freshness recover.')),
 'OPCUA_CONNECTIVITY': Rule('OPC-UA Connectivity Lost','HIGH',
   'PLC reads or the PLC endpoint are unavailable; inspect endpoint probes and bridge logs.',
   ('Check PLC service health and the OPC-UA listener.', 'Inspect bridge logs and endpoint/certificate settings.',
    'Verify the OT connection.', 'Confirm fresh telemetry and successful PLC reads.')),
 'OT_NETWORK_CONNECTIVITY': Rule('OT Network Path Lost','HIGH',
   'An edge path failed while corresponding source endpoints remained reachable in recent monitoring samples.',
   ('Compare edge connectivity with independent Blackbox probes.',
    'Inspect Docker OT network membership and service paths.',
    'Restore only the affected lab network connection.', 'Confirm edge reads/frames and input freshness recover.')),
 'YOLO_MODEL_FAILURE': Rule('YOLO Model Unavailable','WARNING',
   'YOLO is enabled but local model readiness is zero; classical CV remains independent.',
   ('Inspect CV detector model-loading/inference logs.', 'Verify the configured local weight file and permissions.',
    'Check CPU dependencies and model compatibility.', 'Confirm readiness and recent successful inference.')),
 'RESTRICTED_ZONE_VIOLATION': Rule('Person in Restricted Zone','CRITICAL',
   'A model-inferred person bounding box overlapped the configured demonstration zone.',
   ('Inspect the actual video and inferred bounding box.',
    'Follow approved site procedures for personnel near equipment.',
    'Verify zone configuration and possible recognition errors.', 'Confirm the zone signal clears.')),
 'TELEMETRY_LOSS': Rule('Telemetry Input Lost','HIGH',
   'ML input is stale or a telemetry transport endpoint is unavailable.',
   ('Check MQTT broker and bridge health.', 'Inspect OPC-UA reads and telemetry publications.',
    'Check relevant network paths.', 'Confirm fresh telemetry and ML input timestamps.')),
 'SERVICE_OUTAGE': Rule('Platform Service Unavailable','WARNING',
   'A monitored exporter or endpoint is unavailable; the affected resource is recorded in alert labels.',
   ('Identify the failing job/instance from the alert labels.', 'Inspect service health and logs.',
    'Restore the dependency using the local service controls.', 'Confirm the probe/exporter recovers.')),
 'PROCESS_ANOMALY': Rule('Unusual PLC Telemetry','WARNING',
   'IsolationForest reported unusual process telemetry; this is not a diagnosed factory defect.',
   ('Inspect recorded feature values and the anomaly score.', 'Compare deterministic process alerts.',
    'Investigate possible process deviations.', 'Confirm normal fresh telemetry returns.')),
}


def monitoring_value(payload, metric, instance_contains=None, job=None):
    for sample in payload.get('samples', []):
        labels = sample.get('labels', {})
        if labels.get('__name__') != metric:
            continue
        if instance_contains and instance_contains not in labels.get('instance', ''):
            continue
        if job and labels.get('job') != job:
            continue
        return sample['value']
    return None


def classify(name, labels, monitoring):
    direct = {'ProductionLineBlocked':'PRODUCTION_JAM','MotorOverheating':'MOTOR_OVERHEAT',
      'ExcessiveVibration':'EXCESSIVE_VIBRATION','QualityDegradation':'QUALITY_DEGRADATION',
      'ComputerVisionAnomaly':'CAMERA_DEGRADATION','YOLOModelUnavailable':'YOLO_MODEL_FAILURE',
      'PersonInRestrictedZone':'RESTRICTED_ZONE_VIOLATION','MLAnomaly':'PROCESS_ANOMALY',
      'TelemetryStale':'TELEMETRY_LOSS'}
    if name in direct:
        kind = direct[name]
        return kind, kind
    if name == 'OPCUAConnectionLost':
        healthy = monitoring_value(monitoring,'probe_success','opcua-sim:4840') == 1
        kind = 'OT_NETWORK_CONNECTIVITY' if healthy else 'OPCUA_CONNECTIVITY'
        return kind, 'plc-connectivity'
    if name == 'CameraStreamDown':
        healthy = (monitoring_value(monitoring,'probe_success','camera-sim:8082') == 1
                   and monitoring_value(monitoring,'probe_success','mediamtx:8554') == 1
                   and monitoring_value(monitoring,'camera_publisher_up') == 1
                   and monitoring_value(monitoring,'up',job='camera-sim') == 1)
        return ('OT_NETWORK_CONNECTIVITY' if healthy else 'CAMERA_OUTAGE'), 'camera-connectivity'
    if name == 'ExporterDown':
        if labels.get('job') == 'camera-sim':
            return 'CAMERA_OUTAGE', 'camera-connectivity'
        if labels.get('job') == 'opcua-sim':
            return 'OPCUA_CONNECTIVITY', 'plc-connectivity'
    if name == 'IncidentDatabaseUnavailable':
        return 'SERVICE_OUTAGE', 'service:incident-db'
    if name == 'EndpointUnavailable':
        instance = labels.get('instance','')
        if 'opcua-sim:' in instance:
            return 'OPCUA_CONNECTIVITY', 'plc-connectivity'
        if any(target in instance for target in ('camera-sim:', 'mediamtx:')):
            return 'CAMERA_OUTAGE', 'camera-connectivity'
        if 'mqtt:' in instance:
            return 'TELEMETRY_LOSS', 'TELEMETRY_LOSS'
    family='service:' + labels.get('job','unknown') + ':' + labels.get('instance','unknown')
    if len(family)>80:
        family='service:'+hashlib.sha256(family.encode()).hexdigest()
    return 'SERVICE_OUTAGE', family


def jam_compatible(name, cv_payload):
    if name not in JAM_ALERTS:
        return False
    if name == 'ComputerVisionAnomaly' and cv_payload.get('reasons'):
        return 'red-object' in cv_payload['reasons']
    return True
