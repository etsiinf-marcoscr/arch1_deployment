from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from model.order import Order
from database import db
from flask_restful import abort
import util.status as status

orders = Blueprint("orders", __name__)

@orders.route("/api/order", methods=["POST"])
def create_order():
    """Creates a order in the table given a JSON as request.
    """

    if request.content_type == "application/json":
        json = request.get_json()
        if json  == None:
            abort(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, message=f"JSON not valid!")
        new_order = Order.from_json(json)
    else:
        abort(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, message=f"Not a JSON!")

    if new_order == None:
        abort(status.HTTP_400_BAD_REQUEST, message=f"Missing data!")

    try:
        db.session.add(new_order)
        db.session.commit()

    except IntegrityError:
        abort(status.HTTP_400_BAD_REQUEST, message=f"Failed processing order")
    
    return new_order.to_json(), status.HTTP_201_CREATED
        

@orders.route("/api/order", methods=["GET"])
def all_orders():
    """Returns all the orders
       form start (default 0) to end (default 100).
    """
    all_orders = Order.query.all()

    end = request.args.get("end", default=100, type=int)
    start = request.args.get("start", default=0, type=int)
    all_orders = all_orders[start:(start + end)]

    json_data = list(map(Order.to_json, all_orders))
    return jsonify(json_data)

@orders.route("/api/order/<int:id>", methods=["GET"])
def get_order(id: int):
    """Returns the order with a given id.
    """
    order = Order.query.filter(Order.id == id).first()

    if order is None:
        abort(status.HTTP_404_NOT_FOUND, message=f"Order {id} does not exists")
        
    return jsonify(order.to_json())  

@orders.route("/api/order/<int:id>", methods=["DELETE"])
def delete_order(id: int):
    order = Order.query.filter(Order.id == id).first()
    if order == None:
        abort(status.HTTP_404_NOT_FOUND, message=f"Order {id} does not exists")
    
    db.session.delete(order)
    db.session.commit()

    return "", status.HTTP_204_NO_CONTENT

@orders.route("/api/order/<int:id>", methods=["PUT"])
def update_order(id: int):
    order = Order.query.filter(Order.id == id).first()
    if order == None:
        abort(status.HTTP_404_NOT_FOUND, message=f"Order {id} does not exists")
    
    if request.content_type == "application/json":
        order.update_order(request.get_json())
    else:
        abort(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, message=f"Not a JSON or XML!")
    
    db.session.commit()

    return "", status.HTTP_200_OK