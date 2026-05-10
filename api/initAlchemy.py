from database import db
from apiAlchemy import create_api
from flask import json
from model.category import Category
from model.tag import Tag
from model.game import Game
from model.user import User
from model.order import Order
from werkzeug.exceptions import HTTPException
import subprocess

api = create_api()
db.init_app(api)

print(api.url_map)

with api.app_context():
    
    db.drop_all()
    db.create_all()

    category0 = Category(name="PlayStation 4")   
    category1 = Category(name="PlayStation 5")
    category2 = Category(name="XBOX Series")
    category3 = Category(name="XBOX One")
    category4 = Category(name="Nintendo Switch")
    category5 = Category(name="PC")
    db.session.add(category0)
    db.session.add(category1)
    db.session.add(category2)
    db.session.add(category3)
    db.session.add(category4)
    db.session.add(category5)

    tag1 = Tag(name="Action")
    tag2 = Tag(name="RPG")
    tag3 = Tag(name="Simulation")
    tag4 = Tag(name="Fighting")
    tag5 = Tag(name="Shooter")
    tag6 = Tag(name="Visual Novel")
    db.session.add(tag1)
    db.session.add(tag2)
    db.session.add(tag3)
    db.session.add(tag4)
    db.session.add(tag5)
    db.session.add(tag6)

    user1 = User(username='lichking',first_name='Arthas',last_name='Menethil',email='thelichking@warcraft.com', password='sindragosa123', phone='+34123456789')
    user2 = User(username='windrunner',first_name='Sylvanas',last_name='Windrunner',email='thequeen@warcraft.com', password='halfelf605', phone='+34123456781')
    db.session.add(user1)
    db.session.add(user2)

    db.session.commit()

    game1 = Game(name="Persona 5 Royal", available_quantity=10, category=category1, photo_url="https://m.media-amazon.com/images/I/71lQbeZ5LFL.__AC_SX300_SY300_QL70_ML2_.jpg", tags=[tag2,tag6])
    game2 = Game(name="Final Fantasy VII Remake", available_quantity=10, category=category1, photo_url="https://m.media-amazon.com/images/I/81W8CAno24L.__AC_SX300_SY300_QL70_ML2_.jpg", tags=[tag2])
    game3 = Game(name="Resident Evil 4 Remake", available_quantity=10, category=category1, photo_url="https://m.media-amazon.com/images/I/71X0kpkEnML.__AC_SX300_SY300_QL70_ML2_.jpg", tags=[tag1,tag5])
    game4 = Game(name="Hogwarts Legacy", available_quantity=34, category=category1, photo_url="https://m.media-amazon.com/images/I/811m+JsGAzL._AC_SX679_.jpg", tags=[tag1,tag2])
 
    db.session.add(game1)
    db.session.add(game2)
    db.session.add(game3)
    db.session.add(game4)

    db.session.commit()

    order1 = Order(games=[game1,game2], user=user1, address='Campus de Montegancedo, Escuela Técnica Superior de Ingenieros Informáticos', status='sent')
    order2 = Order(games=[game2,game3], user=user2, address='Campus de Montegancedo, CAIT', status='pending')
   
    db.session.add(order1)
    db.session.add(order2)

    db.session.commit()

def handle_exception(e):
    """Return JSON instead of HTML for HTTP errors."""
    # start with the correct headers and status code from the error
    response = e.get_response()
    # replace the body with JSON
    response.data = json.dumps({
        "code": e.code,
        "name": e.name,
        "description": e.description,
    })
    response.content_type = "application/json"
    return response

if __name__ == '__main__':
    api.register_error_handler(Exception, handle_exception)
    api.run(port=8000, debug=True)

@api.after_request
def add_EC2_instance_header(response):
    try:
        ec2_instance_id = subprocess.run(["ec2-metadata", "--instance-id"], capture_output=True)

        if ec2_instance_id != '':
            response.headers["EC2-instance"] = ec2_instance_id.stdout

        ec2_availability_zone = subprocess.run(["ec2-metadata" ,"-z"], capture_output=True)

        if ec2_availability_zone != '':
            response.headers["EC2-availability-zone"] = ec2_availability_zone.stdout
    except:
        None

    return response

