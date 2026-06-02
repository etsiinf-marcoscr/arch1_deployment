import boto3
import time
from time import sleep
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
# 1. ECR - borrar repositorios al principio (sin dependencias)
# ===========================================================================

title("1. Repositorios ECR")

for repo_name in ["gamestore-postgres", "gamestore-api", "gamestore-swagger"]:
    try:
        ecr.delete_repository(repositoryName=repo_name, force=True)
        ok(f"Repositorio ECR {repo_name} eliminado")
    except ecr.exceptions.RepositoryNotFoundException:
        skip(f"Repositorio ECR {repo_name}")


# ===========================================================================
# 2. Servicios ECS - reducir a 0 y eliminar
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
# 4. Task definitions - desregistrar todas las revisiones y borarlas
# ===========================================================================

title("4. Task Definitions")

for family in ["postgres", "api", "swagger"]:
    try:
        paginator = ecs.get_paginator("list_task_definitions")

        active_arns = []
        for page in paginator.paginate(familyPrefix=family, status="ACTIVE"):
            active_arns.extend(page["taskDefinitionArns"])

        for arn in active_arns:
            ecs.deregister_task_definition(taskDefinition=arn)
            ok(f"Task definition desregistrada: {arn.split('/')[-1]}")

        if not active_arns:
            skip(f"Task definitions activas familia {family}")

        inactive_arns = []
        for page in paginator.paginate(familyPrefix=family, status="INACTIVE"):
            inactive_arns.extend(page["taskDefinitionArns"])

        for i in range(0, len(inactive_arns), 10):
            batch = inactive_arns[i:i + 10]
            resp = ecs.delete_task_definitions(taskDefinitions=batch)
            for td in resp.get("taskDefinitions", []):
                ok(f"Task definition borrada: {td['taskDefinitionArn'].split('/')[-1]}")
            for failure in resp.get("failures", []):
                print(f"  ! No se pudo borrar {failure['arn']}: {failure['reason']}")

        if not inactive_arns:
            skip(f"Task definitions inactivas familia {family}")

    except Exception as e:
        print(f"  ! Error procesando familia {family}: {e}")


# ===========================================================================
# 5. ALB - listener, ALB, y target groups (por tag + por nombre)
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

    listeners = elbv2.describe_listeners(LoadBalancerArn=alb_arn)["Listeners"]
    for l in listeners:
        elbv2.delete_listener(ListenerArn=l["ListenerArn"])
        ok(f"Listener eliminado")

    elbv2.delete_load_balancer(LoadBalancerArn=alb_arn)
    ok(f"ALB {alb['LoadBalancerName']} eliminado, esperando...")
    waiter = elbv2.get_waiter("load_balancers_deleted")
    waiter.wait(LoadBalancerArns=[alb_arn])
    ok("ALB eliminado completamente")

if not albs_tagged:
    skip("ALB")

# Target groups: buscar por tag Y por nombre conocido para capturar huérfanos
print("\n  Buscando target groups (asociados y huérfanos)...")

all_tgs = elbv2.describe_target_groups()["TargetGroups"]

tgs_to_delete = []
for tg in all_tgs:
    tg_arn = tg["TargetGroupArn"]
    # Por nombre conocido
    if tg["TargetGroupName"] in ("api-target",):
        tgs_to_delete.append(tg_arn)
        continue
    # Por tag
    try:
        tags = elbv2.describe_tags(ResourceArns=[tg_arn])["TagDescriptions"][0]["Tags"]
        if any(t["Key"] == TAG_KEY and t["Value"] == TAG_VALUE for t in tags):
            tgs_to_delete.append(tg_arn)
    except Exception:
        pass

for tg_arn in tgs_to_delete:
    for intento in range(6):
        try:
            elbv2.delete_target_group(TargetGroupArn=tg_arn)
            ok(f"Target group eliminado: {tg_arn.split('/')[-2]}")
            break
        except elbv2.exceptions.ResourceInUseException:
            print(f"    En uso, esperando 5s... (intento {intento+1}/6)")
            time.sleep(5)
        except Exception as e:
            print(f"    Error: {e}")
            break
    else:
        print(f"  ! No se pudo borrar el target group tras varios intentos")

if not tgs_to_delete:
    skip("Target groups")


# ===========================================================================
# 6. VPC Endpoints - borrar y esperar con un único describe al final
# ===========================================================================

title("6. VPC Endpoints")

endpoints = ec2.describe_vpc_endpoints(Filters=TAG_FILTER)["VpcEndpoints"]
# Filtrar solo los que no esten ya eliminados
ep_ids = [
    e["VpcEndpointId"] for e in endpoints
    if e["State"] not in ("deleted", "deleting")
]

if ep_ids:
    ec2.delete_vpc_endpoints(VpcEndpointIds=ep_ids)
    ok(f"Solicitud de borrado enviada para {len(ep_ids)} endpoint(s)")

    print("  Esperando que los endpoints se eliminen...")
    while True:
        try:
            still_active = ec2.describe_vpc_endpoints(
                VpcEndpointIds=ep_ids,
                Filters=[{"Name": "vpc-endpoint-state", "Values": ["deleting", "pending", "available"]}]
            )["VpcEndpoints"]
            if not still_active:
                break
            print(f"    Quedan {len(still_active)} endpoint(s) activos, esperando 10s...")
        except ec2.exceptions.ClientError as e:
            if "InvalidVpcEndpointId.NotFound" in str(e):
                # Todos los endpoints han desaparecido: borrado completado
                break
            raise
        time.sleep(10)
    ok("Todos los endpoints eliminados")
else:
    skip("VPC Endpoints")


# ===========================================================================
# 7. Internet Gateway - detach + delete
# ===========================================================================

title("7. Internet Gateway (esperando 60s tras eliminar endpoints)")

sleep(60)  # Esperar un poco para que AWS actualice el estado de los recursos tras eliminar endpoints

vpcs = ec2.describe_vpcs(Filters=TAG_FILTER)["Vpcs"]
vpc_id = vpcs[0]["VpcId"] if vpcs else None

if vpc_id:
    # Liberar cualquier IP pública/EIP mapeada en la VPC antes de desconectar el IGW
    enis = ec2.describe_network_interfaces(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
    )["NetworkInterfaces"]

    for eni in enis:
        assoc = eni.get("Association")
        if assoc:
            allocation_id = assoc.get("AllocationId")
            association_id = assoc.get("AssociationId")
            # Si tiene AssociationId es que la IP pública está asociada a esta ENI, desasociar primero
            if association_id:
                try:
                    ec2.disassociate_address(AssociationId=association_id)
                    print(f"    IP pública desasociada de ENI {eni['NetworkInterfaceId']}")
                except Exception as e:
                    print(f"    No se pudo desasociar IP: {e}")
            # Si tiene AllocationId es una EIP, liberar también
            if allocation_id:
                try:
                    ec2.release_address(AllocationId=allocation_id)
                    print(f"    EIP {allocation_id} liberada")
                except Exception as e:
                    print(f"    No se pudo liberar EIP: {e}")

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
        for intento in range(12):  # hasta 60 segundos de espera por subnet
            try:
                ec2.delete_subnet(SubnetId=subnet["SubnetId"])
                ok(f"Subnet {subnet['SubnetId']} eliminada")
                break
            except ec2.exceptions.ClientError as e:
                if "DependencyViolation" in str(e):
                    # Buscar ENIs huérfanos en esta subnet y eliminarlos
                    enis = ec2.describe_network_interfaces(
                        Filters=[{"Name": "subnet-id", "Values": [subnet["SubnetId"]]}]
                    )["NetworkInterfaces"]
                    if enis:
                        for eni in enis:
                            eni_id = eni["NetworkInterfaceId"]
                            status = eni["Status"]
                            print(f"    ENI huérfano detectado: {eni_id} (estado: {status})")
                            # Solo se pueden borrar ENIs en estado 'available'
                            if status == "available":
                                try:
                                    ec2.delete_network_interface(NetworkInterfaceId=eni_id)
                                    print(f"    ENI {eni_id} eliminado")
                                except Exception as e2:
                                    print(f"    No se pudo borrar ENI: {e2}")
                            else:
                                print(f"    ENI {eni_id} no está disponible aún, esperando...")
                    else:
                        print(f"    Sin ENIs visibles, esperando liberación... (intento {intento+1}/12)")
                    time.sleep(5)
                else:
                    raise
        else:
            print(f"  ! No se pudo borrar subnet {subnet['SubnetId']} tras varios intentos")
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
print("  Recuerde eliminar los registros de Cloudwatch en caso de no necesitarlos.")
print("  Recuerde eliminar la máquina EC2 de bastión en caso de haberla utilizado para el despliegue.")
print()