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
# 1. Servicios ECS — reducir a 0 y eliminar
# ===========================================================================

title("1. Servicios ECS")

try:
    services = ecs.list_services(cluster=CLUSTER)["serviceArns"]
    if services:
        # Primero escalar a 0 todos para liberar ENIs y target groups
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
# 2. Cluster ECS
# ===========================================================================

title("2. Cluster ECS")

try:
    ecs.delete_cluster(cluster=CLUSTER)
    ok(f"Cluster {CLUSTER} eliminado")
except ecs.exceptions.ClusterNotFoundException:
    skip("Cluster ECS")


# ===========================================================================
# 3. Task definitions — desregistrar todas las revisiones
# ===========================================================================

title("3. Task Definitions")

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
# 4. ALB — listener, target group y load balancer
# ===========================================================================

title("4. ALB")

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

    # Listeners
    listeners = elbv2.describe_listeners(LoadBalancerArn=alb_arn)["Listeners"]
    for l in listeners:
        elbv2.delete_listener(ListenerArn=l["ListenerArn"])
        ok(f"Listener eliminado: {l['ListenerArn'].split('/')[-1]}")

    # Target groups
    tgs = elbv2.describe_target_groups(LoadBalancerArn=alb_arn)["TargetGroups"]
    for tg in tgs:
        elbv2.delete_target_group(TargetGroupArn=tg["TargetGroupArn"])
        ok(f"Target group eliminado: {tg['TargetGroupName']}")

    # ALB
    elbv2.delete_load_balancer(LoadBalancerArn=alb_arn)
    ok(f"ALB eliminado: {alb['LoadBalancerName']}")

    print("  Esperando a que el ALB se elimine completamente...")
    waiter = elbv2.get_waiter("load_balancers_deleted")
    waiter.wait(LoadBalancerArns=[alb_arn])
    ok("ALB eliminado completamente")

if not albs_tagged:
    skip("ALB")


# ===========================================================================
# 5. VPC Endpoints
# ===========================================================================

title("5. VPC Endpoints")

endpoints = ec2.describe_vpc_endpoints(Filters=TAG_FILTER)["VpcEndpoints"]
if endpoints:
    ep_ids = [e["VpcEndpointId"] for e in endpoints]
    ec2.delete_vpc_endpoints(VpcEndpointIds=ep_ids)
    ok(f"Endpoints eliminados: {ep_ids}")

    print("  Esperando que los endpoints se eliminen...")
    while True:
        pending = ec2.describe_vpc_endpoints(
            VpcEndpointIds=ep_ids,
            Filters=[{"Name": "vpc-endpoint-state", "Values": ["deleting", "pending"]}]
        )["VpcEndpoints"]
        if not pending:
            break
        time.sleep(10)
    ok("Endpoints eliminados completamente")
else:
    skip("VPC Endpoints")


# ===========================================================================
# 6. Internet Gateway — detach + delete
# ===========================================================================

title("6. Internet Gateway")

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
# 7. Subnets
# ===========================================================================

title("7. Subnets")

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
# 8. Route Tables
# ===========================================================================

title("8. Route Tables")

if vpc_id:
    rts = ec2.describe_route_tables(Filters=TAG_FILTER)["RouteTables"]
    for rt in rts:
        # La route table main no se puede borrar explícitamente
        is_main = any(a.get("Main") for a in rt.get("Associations", []))
        if is_main:
            skip(f"Route table main {rt['RouteTableId']}")
            continue
        # Desasociar primero
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
# 9. Security Groups
# ===========================================================================

title("9. Security Groups")

if vpc_id:
    sgs = ec2.describe_security_groups(Filters=TAG_FILTER)["SecurityGroups"]
    # El SG por defecto de la VPC no se puede borrar
    sgs = [sg for sg in sgs if sg["GroupName"] != "default"]

    # Primero revocar todas las reglas de entrada que referencian otros SGs
    # del proyecto (evita el error de dependencia circular)
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
# 10. VPC
# ===========================================================================

title("10. VPC")

if vpc_id:
    ec2.delete_vpc(VpcId=vpc_id)
    ok(f"VPC {vpc_id} eliminada")
else:
    skip("VPC")


# ===========================================================================
# 11. ECR — borrar repositorios con todas sus imágenes
# ===========================================================================

title("11. Repositorios ECR")

for repo_name in ["gamestore-postgres", "gamestore-api", "gamestore-swagger"]:
    try:
        # force=True borra el repo aunque tenga imágenes
        ecr.delete_repository(repositoryName=repo_name, force=True)
        ok(f"Repositorio ECR {repo_name} eliminado")
    except ecr.exceptions.RepositoryNotFoundException:
        skip(f"Repositorio ECR {repo_name}")


# ===========================================================================
# Resumen
# ===========================================================================

title("TEARDOWN COMPLETADO")
print("  Todos los recursos de gamestore han sido eliminados.")
print()
