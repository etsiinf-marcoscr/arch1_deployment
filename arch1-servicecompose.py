import boto3
import time
import subprocess

# ---------------------------------------------------------------------------
# Dependencias de entorno: credenciales AWS configuradas (ej: con aws configure) y Docker instalado y corriendo localmente (para build/push de imágenes).
# IMPORTANTE: tener al mismo nivel del script las carpetas "api" y "swagger" con sus respectivos Dockerfiles y código.
# ---------------------------------------------------------------------------

REGION = "us-east-1"

ec2  = boto3.client("ec2",  region_name=REGION)
ecs  = boto3.client("ecs",  region_name=REGION)
elbv2 = boto3.client("elbv2", region_name=REGION)
sts  = boto3.client("sts")

ACCOUNT = sts.get_caller_identity()["Account"]
ECR_ROOT = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def render_template(template_path, output_path, old_value, new_value):
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace(old_value, new_value)
    content = content.replace("\r\n", "\n")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

def ecr_login():
    print("Login ECR")
    subprocess.run(
        f"aws ecr get-login-password --region {REGION} "
        f"| docker login --username AWS --password-stdin {ECR_ROOT}",
        shell=True, check=True
    )

def build_push_postgres():
    repo = f"{ECR_ROOT}/gamestore-postgres:latest"
    print("Build/push postgres")
    subprocess.run("docker pull postgres:15",                          shell=True, check=True)
    subprocess.run(f"docker tag postgres:15 {repo}",                  shell=True, check=True)
    subprocess.run(f"docker push {repo}",                             shell=True, check=True)

def build_push_api():
    repo = f"{ECR_ROOT}/gamestore-api:latest"
    print("Build/push API")
    subprocess.run("docker build -t gamestore-api ./api",             shell=True, check=True)
    subprocess.run(f"docker tag gamestore-api:latest {repo}",         shell=True, check=True)
    subprocess.run(f"docker push {repo}",                             shell=True, check=True)

def build_push_swagger():
    repo = f"{ECR_ROOT}/gamestore-swagger:latest"
    print("Build/push Swagger")
    subprocess.run("docker build -t gamestore-swagger ./swagger",     shell=True, check=True)
    subprocess.run(f"docker tag gamestore-swagger:latest {repo}",     shell=True, check=True)
    subprocess.run(f"docker push {repo}",                             shell=True, check=True)

def wait_for_task_running(cluster, service):
    print(f"Esperando que el task '{service}' esté RUNNING...")
    while True:
        task_arns = ecs.list_tasks(cluster=cluster, serviceName=service)["taskArns"]
        if task_arns:
            task = ecs.describe_tasks(cluster=cluster, tasks=task_arns)["tasks"][0]
            status = task["lastStatus"]
            print(f"  Estado actual: {status}")
            if status == "RUNNING":
                return task
        time.sleep(10)

def get_task_private_ip(task):
    eni_id = next(
        d["value"]
        for d in task["attachments"][0]["details"]
        if d["name"] == "networkInterfaceId"
    )
    eni_desc = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    return eni_desc["NetworkInterfaces"][0]["PrivateIpAddress"]

def get_task_public_ip(task):
    eni_id = next(
        d["value"]
        for d in task["attachments"][0]["details"]
        if d["name"] == "networkInterfaceId"
    )
    eni_desc = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    return eni_desc["NetworkInterfaces"][0]["Association"]["PublicIp"]


# ===========================================================================
# 1. ECR — repositorios e imágenes base
# ===========================================================================

ecr = boto3.client("ecr", region_name=REGION)

for repo_name in ["gamestore-postgres", "gamestore-api", "gamestore-swagger"]:
    try:
        ecr.create_repository(repositoryName=repo_name)
        print(f"Repositorio creado: {repo_name}")
    except ecr.exceptions.RepositoryAlreadyExistsException:
        print(f"Repositorio ya existe: {repo_name}")

ecr_login()
build_push_postgres()


# ===========================================================================
# 2. Red: VPC, subnets, IGW, routing
# ===========================================================================

print("\nCreando VPC")
vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
print("VPC:", vpc_id)

print("Creando subnets")

# Obtener AZs disponibles en la región
azs = ec2.describe_availability_zones(
    Filters=[{"Name": "state", "Values": ["available"]}]
)["AvailabilityZones"]

az1 = azs[0]["ZoneName"]
az2 = azs[1]["ZoneName"]

public_subnet  = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.1.0/24", AvailabilityZone=az1)["Subnet"]["SubnetId"]
public_subnet2 = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.3.0/24", AvailabilityZone=az2)["Subnet"]["SubnetId"]
private_subnet = ec2.create_subnet(VpcId=vpc_id, CidrBlock="10.0.2.0/24", AvailabilityZone=az1)["Subnet"]["SubnetId"]

print(f"  public_subnet  → {az1}")
print(f"  public_subnet2 → {az2}")
print(f"  private_subnet → {az1}")

print("Creando IGW")
igw = ec2.create_internet_gateway()["InternetGateway"]["InternetGatewayId"]
ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc_id)

print("Routing público")
rt_public = ec2.create_route_table(VpcId=vpc_id)["RouteTable"]["RouteTableId"]
ec2.create_route(RouteTableId=rt_public, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
ec2.associate_route_table(SubnetId=public_subnet,  RouteTableId=rt_public)
ec2.associate_route_table(SubnetId=public_subnet2, RouteTableId=rt_public)

print("Routing privado")
rt_private = ec2.create_route_table(VpcId=vpc_id)["RouteTable"]["RouteTableId"]
ec2.associate_route_table(SubnetId=private_subnet, RouteTableId=rt_private)


# ===========================================================================
# 3. Security groups
# ===========================================================================

print("Creando security groups")

def make_sg(name, desc):
    return ec2.create_security_group(GroupName=name, Description=desc, VpcId=vpc_id)["GroupId"]

swagger_sg  = make_sg("swagger-sg",  "swagger")
backend_sg  = make_sg("backend-sg",  "backend")
alb_sg      = make_sg("alb-sg",      "alb")
endpoint_sg = make_sg("endpoint-sg", "endpoint")

# swagger: puerto 8080 público
ec2.authorize_security_group_ingress(GroupId=swagger_sg, IpPermissions=[{
    "IpProtocol": "tcp", "FromPort": 8080, "ToPort": 8080,
    "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
}])

# alb: puerto 80 público
ec2.authorize_security_group_ingress(GroupId=alb_sg, IpPermissions=[{
    "IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
    "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
}])

# backend: 5000 desde alb-sg, 5432 desde backend-sg (postgres)
ec2.authorize_security_group_ingress(GroupId=backend_sg, IpPermissions=[
    {"IpProtocol": "tcp", "FromPort": 5000, "ToPort": 5000,
     "UserIdGroupPairs": [{"GroupId": alb_sg}]},
    {"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
     "UserIdGroupPairs": [{"GroupId": backend_sg}]}
])

# endpoint: 443 desde backend-sg (para que los tasks privados alcancen ECR/logs)
ec2.authorize_security_group_ingress(GroupId=endpoint_sg, IpPermissions=[{
    "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
    "UserIdGroupPairs": [
        {"GroupId": backend_sg},
        {"GroupId": swagger_sg}
    ]
}])


# ===========================================================================
# 4. VPC Endpoints
# ===========================================================================

print("Creando VPC endpoints")

# Gateway S3 (para que Fargate descargue capas de imagen)
ec2.create_vpc_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.s3",
    VpcEndpointType="Gateway",
    RouteTableIds=[rt_private]
)

ec2.create_vpc_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.ecr.api",
    VpcEndpointType="Interface",
    SubnetIds=[private_subnet],
    SecurityGroupIds=[endpoint_sg],
    PrivateDnsEnabled=True
)

ec2.create_vpc_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.ecr.dkr",
    VpcEndpointType="Interface",
    SubnetIds=[private_subnet],
    SecurityGroupIds=[endpoint_sg],
    PrivateDnsEnabled=True
)

ec2.create_vpc_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.logs",
    VpcEndpointType="Interface",
    SubnetIds=[private_subnet],
    SecurityGroupIds=[endpoint_sg],
    PrivateDnsEnabled=True
)

# ===========================================================================
# 4.5 IAM — execution role (usando LabRole del entorno de laboratorio)
# ===========================================================================

iam = boto3.client("iam")
execution_role_arn = iam.get_role(RoleName="LabRole")["Role"]["Arn"]
print("Usando execution role:", execution_role_arn)

# ===========================================================================
# 5. Cluster ECS + servicio Postgres
# ===========================================================================

print("Creando cluster ECS")
ecs.create_cluster(clusterName="gamestore-cluster")

print("Registrando task postgres")
ecs.register_task_definition(
    family="postgres",
    executionRoleArn=execution_role_arn,
    networkMode="awsvpc",
    requiresCompatibilities=["FARGATE"],
    cpu="256", memory="512",
    containerDefinitions=[{
        "name": "postgres",
        "image": f"{ECR_ROOT}/gamestore-postgres:latest",
        "portMappings": [{"containerPort": 5432}],
        "environment": [
            {"name": "POSTGRES_DB",       "value": "gamestore"},
            {"name": "POSTGRES_USER",     "value": "gamestore"},
            {"name": "POSTGRES_PASSWORD", "value": "gamestorepass"}
        ]
    }]
)

print("Creando servicio postgres")
ecs.create_service(
    cluster="gamestore-cluster",
    serviceName="postgres",
    taskDefinition="postgres",
    desiredCount=1,
    launchType="FARGATE",
    networkConfiguration={"awsvpcConfiguration": {
        "subnets": [private_subnet],
        "securityGroups": [backend_sg],
        "assignPublicIp": "DISABLED"
    }}
)

# Espera activa hasta que el task esté RUNNING
postgres_task = wait_for_task_running("gamestore-cluster", "postgres")
postgres_ip   = get_task_private_ip(postgres_task)
print("IP privada postgres:", postgres_ip)


# ===========================================================================
# 6. Build API
# ===========================================================================

render_template(
    "api/wait-for-db.sh.template",
    "api/wait-for-db.sh",
    "POSTGRES_IP",
    postgres_ip
)

build_push_api()

print("Registrando task API")
ecs.register_task_definition(
    family="api",
    executionRoleArn=execution_role_arn,
    networkMode="awsvpc",
    requiresCompatibilities=["FARGATE"],
    cpu="256", memory="512",
    containerDefinitions=[{
        "name": "api",
        "image": f"{ECR_ROOT}/gamestore-api:latest",
        "portMappings": [{"containerPort": 5000}],
        "environment": [{
            "name":  "DATABASE_URI",
            "value": f"postgresql://gamestore:gamestorepass@{postgres_ip}:5432/gamestore"
        }]
    }]
)


# ===========================================================================
# 7. ALB + servicio API
# ===========================================================================

print("Creando ALB")
alb_resp = elbv2.create_load_balancer(
    Name="api-alb",
    Subnets=[public_subnet, public_subnet2],
    SecurityGroups=[alb_sg],
    Scheme="internet-facing",
    Type="application",
    IpAddressType="ipv4"
)
alb_arn = alb_resp["LoadBalancers"][0]["LoadBalancerArn"]
alb_dns = alb_resp["LoadBalancers"][0]["DNSName"]
print("ALB DNS:", alb_dns)

tg_arn = elbv2.create_target_group(
    Name="api-target",
    Protocol="HTTP",
    Port=5000,
    VpcId=vpc_id,
    TargetType="ip",
    HealthCheckPath="/api/game"
)["TargetGroups"][0]["TargetGroupArn"]

elbv2.create_listener(
    LoadBalancerArn=alb_arn,
    Protocol="HTTP", Port=80,
    DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}]
)

print("Creando servicio API")
ecs.create_service(
    cluster="gamestore-cluster",
    serviceName="api",
    taskDefinition="api",
    desiredCount=1,
    launchType="FARGATE",
    loadBalancers=[{
        "targetGroupArn": tg_arn,
        "containerName": "api",
        "containerPort": 5000
    }],
    networkConfiguration={"awsvpcConfiguration": {
        "subnets": [private_subnet],
        "securityGroups": [backend_sg],
        "assignPublicIp": "DISABLED"
    }}
)

ecs.update_service(
    cluster="gamestore-cluster",
    service="api",
    forceNewDeployment=True
)


# ===========================================================================
# 8. Build Swagger
# ===========================================================================

render_template(
    "swagger/swagger-config.json.template",
    "swagger/swagger-config.json",
    "ALB_URL",
    f"http://{alb_dns}/api"
)

build_push_swagger()

print("Registrando task Swagger")
ecs.register_task_definition(
    family="swagger",
    executionRoleArn=execution_role_arn,
    networkMode="awsvpc",
    requiresCompatibilities=["FARGATE"],
    cpu="256", memory="512",
    containerDefinitions=[{
        "name": "swagger",
        "image": f"{ECR_ROOT}/gamestore-swagger:latest",
        "portMappings": [{"containerPort": 8080}]
    }]
)

print("Creando servicio Swagger")
ecs.create_service(
    cluster="gamestore-cluster",
    serviceName="swagger",
    taskDefinition="swagger",
    desiredCount=1,
    launchType="FARGATE",
    networkConfiguration={"awsvpcConfiguration": {
        "subnets": [public_subnet],
        "securityGroups": [swagger_sg],
        "assignPublicIp": "ENABLED"
    }}
)

ecs.update_service(
    cluster="gamestore-cluster",
    service="swagger",
    forceNewDeployment=True
)


# ===========================================================================
# Resumen final
# ===========================================================================

swagger_task   = wait_for_task_running("gamestore-cluster", "swagger")
swagger_pub_ip = get_task_public_ip(swagger_task)

print("\n=== DESPLIEGUE TERMINADO ===")
print(f"API:     http://{alb_dns}/api")
print(f"Swagger: http://{swagger_pub_ip}:8080")