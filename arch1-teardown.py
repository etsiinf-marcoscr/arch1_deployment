import boto3
import time

# ---------------------------------------------------------------------------
# Borra todos los recursos del proyecto gamestore en el orden correcto.
# Busca recursos por el tag Stack=arch1.
# ---------------------------------------------------------------------------

REGION     = "us-east-1"
TAG_KEY    = "Stack"
TAG_VALUE  = "arch1"
CLUSTER    = "gamestore-cluster"

ec2   = boto3.client("ec2",   region_name=REGION)
ecs   = boto3.client("ecs",   region_name=REGION)
elbv2 = boto3.client("elbv2", region_name=REGION)
ecr   = boto3.client("ecr",   region_name=REGION)

TAG_FILTER = [{"Name": f"tag:{TAG_KEY}", "Values": [TAG_VALUE]}]


def title(msg):
    print(f"\n{'='*50}")
    print(f"  {msg}")
    print(f"{'='*50}")

def ok(msg):
    print(f"  ✓ {msg}")

def skip(msg):
    print(f"  - {msg} (no encontrado, omitiendo)")


# ===========================================================================
# 1. ECR — borrar repositorios al principio (sin dependencias)
# ===========================================================================

title("1. Repositorios ECR")

for repo_name in ["gamestore-postgres", "gamestore-api", "gamestore-swagger"]:
    try:
        ecr.delete_repository(repositoryName=repo_name, force=True)
        ok(f"Repositorio ECR {repo_name} eliminado")
    except ecr.exceptions.RepositoryNotFoundException:
        skip(f"Repositorio ECR {repo_name}")


# ===========================================================================
# 2. Servicios ECS — reducir a 0 y eliminar
# ===========================================================================

title("2. Servicios ECS")

try:
    services = ecs.list_services(cluster=CLUSTER)["serviceArns"]
    if services:
        for svc_arn in services:
            svc_name = svc_arn.split("/")[-1]
            ecs.update_service(cluster=CLUSTER, service=svc_name, desiredCount=0)
            ok(f"Servicio {svc_name} escalado a 0")

        print("  Esperando que los tasks se detengan...")
        time.sleep(30)

        for svc_arn in services:
            svc_name = svc_arn.split("/")[-1]
            ecs.delete_service(cluster=CLUSTER, service=svc_name, force=True)
            ok(f"Servicio {svc_name} eliminado")
    else:
        skip("Servicios ECS")
except ecs.exceptions.ClusterNotFoundException:
    skip("Cluster ECS (no existe)")


# ===========================================================================
# 3. Cluster ECS
# ===========================================================================

title("3. Cluster ECS")

try:
    ecs.delete_cluster(cluster=CLUSTER)
    ok(f"Cluster {CLUSTER} eliminado")
except ecs.exceptions.ClusterNotFoundException:
    skip("Cluster ECS")


# ===========================================================================
# 4. Task definitions — desregistrar todas las revisiones
# ===========================================================================

title("4. Task Definitions")

for family in ["postgres", "api", "swagger"]:
    try:
        paginator = ecs.get_paginator("list_task_definitions")
        arns = []
        for page in paginator.paginate(familyPrefix=family, status="ACTIVE"):
            arns.extend(page["taskDefinitionArns"])
        for arn in arns:
            ecs.deregister_task_definition(taskDefinition=arn)
            ok(f"Task definition desregistrada: {arn.split('/')[-1]}")
        if not arns:
            skip(f"Task definitions familia {family}")
    except Exception as e:
        print(f"  ! Error desregistrando {family}: {e}")


# ===========================================================================
# 5. ALB — listener, ALB y luego target group
#    Orden importante: borrar listener y ALB antes que el target group
# ===========================================================================

title("5. ALB")

albs = elbv2.describe_load_balancers()["LoadBalancers"]
albs_tagged = [
    a for a in albs
    if any(
        t["Key"] == TAG_KEY and t["Value"] == TAG_VALUE
        for t in elbv2.describe_tags(ResourceArns=[a["LoadBalancerArn"]])
                       ["TagDescriptions"][0]["Tags"]
    )
]

for alb in albs_tagged:
    alb_arn = alb["LoadBalancerArn"]

    # 1. Listeners primero
    listeners = elbv2.describe_listeners(LoadBalancerArn=alb_arn)["Listeners"]
    for l in listeners:
        elbv2.delete_listener(ListenerArn=l["ListenerArn"])
        ok(f"Listener eliminado")

    # 2. Recoger ARNs de target groups ANTES de borrar el ALB
    tg_arns = [
        tg["TargetGroupArn"]
        for tg in elbv2.describe_target_groups(LoadBalancerArn=alb_arn)["TargetGroups"]
    ]

    # 3. Borrar el ALB y esperar
    elbv2.delete_load_balancer(LoadBalancerArn=alb_arn)
    ok(f"ALB {alb['LoadBalancerName']} eliminado, esperando...")
    waiter = elbv2.get_waiter("load_balancers_deleted")
    waiter.wait(LoadBalancerArns=[alb_arn])
    ok("ALB eliminado completamente")

    # 4. Borrar target groups DESPUÉS de que el ALB haya desaparecido
    for tg_arn in tg_arns:
        try:
            elbv2.delete_target_group(TargetGroupArn=tg_arn)
            ok(f"Target group eliminado: {tg_arn.split('/')[-2]}")
        except Exception as e:
            print(f"  ! Error borrando target group: {e}")

if not albs_tagged:
    skip("ALB")


# ===========================================================================
# 6. VPC Endpoints — borrar y esperar con un único describe al final
# ===========================================================================

title("6. VPC Endpoints")

endpoints = ec2.describe_vpc_endpoints(Filters=TAG_FILTER)["VpcEndpoints"]
# Filtrar solo los que no estén ya eliminados
ep_ids = [
    e["VpcEndpointId"] for e in endpoints
    if e["State"] not in ("deleted", "deleting")
]

if ep_ids:
    ec2.delete_vpc_endpoints(VpcEndpointIds=ep_ids)
    ok(f"Solicitud de borrado enviada para {len(ep_ids)} endpoint(s)")

    print("  Esperando que los endpoints se eliminen...")
    while True:
        # Una sola llamada describe, sin re-filtrar por tag (ya tenemos los IDs)
        still_active = ec2.describe_vpc_endpoints(
            VpcEndpointIds=ep_ids,
            Filters=[{"Name": "vpc-endpoint-state", "Values": ["deleting", "pending", "available"]}]
        )["VpcEndpoints"]
        if not still_active:
            break
        print(f"    Quedan {len(still_active)} endpoint(s) activos, esperando 10s...")
        time.sleep(10)
    ok("Todos los endpoints eliminados")
else:
    skip("VPC Endpoints")


# ===========================================================================
# 7. Internet Gateway — detach + delete
# ===========================================================================

title("7. Internet Gateway")

vpcs = ec2.describe_vpcs(Filters=TAG_FILTER)["Vpcs"]
vpc_id = vpcs[0]["VpcId"] if vpcs else None

if vpc_id:
    igws = ec2.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
    )["InternetGateways"]
    for igw in igws:
        igw_id = igw["InternetGatewayId"]
        ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
        ec2.delete_internet_gateway(InternetGatewayId=igw_id)
        ok(f"IGW {igw_id} desconectado y eliminado")
    if not igws:
        skip("IGW")
else:
    skip("VPC (y por tanto IGW)")


# ===========================================================================
# 8. Subnets
# ===========================================================================

title("8. Subnets")

if vpc_id:
    subnets = ec2.describe_subnets(Filters=TAG_FILTER)["Subnets"]
    for subnet in subnets:
        ec2.delete_subnet(SubnetId=subnet["SubnetId"])
        ok(f"Subnet {subnet['SubnetId']} eliminada")
    if not subnets:
        skip("Subnets")
else:
    skip("Subnets (sin VPC)")


# ===========================================================================
# 9. Route Tables
# ===========================================================================

title("9. Route Tables")

if vpc_id:
    rts = ec2.describe_route_tables(Filters=TAG_FILTER)["RouteTables"]
    for rt in rts:
        is_main = any(a.get("Main") for a in rt.get("Associations", []))
        if is_main:
            skip(f"Route table main {rt['RouteTableId']}")
            continue
        for assoc in rt.get("Associations", []):
            if not assoc.get("Main"):
                ec2.disassociate_route_table(AssociationId=assoc["RouteTableAssociationId"])
        ec2.delete_route_table(RouteTableId=rt["RouteTableId"])
        ok(f"Route table {rt['RouteTableId']} eliminada")
    if not rts:
        skip("Route Tables")
else:
    skip("Route Tables (sin VPC)")


# ===========================================================================
# 10. Security Groups
# ===========================================================================

title("10. Security Groups")

if vpc_id:
    sgs = ec2.describe_security_groups(Filters=TAG_FILTER)["SecurityGroups"]
    sgs = [sg for sg in sgs if sg["GroupName"] != "default"]

    for sg in sgs:
        if sg["IpPermissions"]:
            try:
                ec2.revoke_security_group_ingress(
                    GroupId=sg["GroupId"],
                    IpPermissions=sg["IpPermissions"]
                )
            except Exception:
                pass

    for sg in sgs:
        try:
            ec2.delete_security_group(GroupId=sg["GroupId"])
            ok(f"SG {sg['GroupName']} ({sg['GroupId']}) eliminado")
        except Exception as e:
            print(f"  ! No se pudo borrar {sg['GroupName']}: {e}")
    if not sgs:
        skip("Security Groups")
else:
    skip("Security Groups (sin VPC)")


# ===========================================================================
# 11. VPC
# ===========================================================================

title("11. VPC")

if vpc_id:
    ec2.delete_vpc(VpcId=vpc_id)
    ok(f"VPC {vpc_id} eliminada")
else:
    skip("VPC")


# ===========================================================================
# Resumen
# ===========================================================================

title("TEARDOWN COMPLETADO")
print("  Todos los recursos de gamestore han sido eliminados.")
print()