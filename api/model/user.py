from database import db
from werkzeug.exceptions import NotFound

class User(db.Model):

    # Table name and columns
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(250), unique=True, nullable=False)
    first_name = db.Column(db.String(250), unique=False, nullable=False)
    last_name = db.Column(db.String(250), unique=False, nullable=False)
    email = db.Column(db.String(250), unique=False, nullable=False)
    password = db.Column(db.String(250), unique=False, nullable=False)
    phone = db.Column(db.String(250), unique=False, nullable=False)

    def __init__(self, username : str, first_name : str, last_name : str, email : str, password : str, phone : str) -> None:
        """Adds a user in the table.
        """
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.password = password
        self.phone = phone


    def to_json(self) -> dict:
        """From user to JSON.
        """
        resource = {
            "id": self.id,
            "username" : self.username,
            "firstName" : self.first_name,
            "lastName" : self.last_name,
            "email" : self.email,
            "phone" : self.phone
        }
        return resource
    
    @staticmethod
    def from_json(data: dict) -> None:
        """From JSON to user.

        Args: 
            data: input JSON.
        """
        try:
            my_user = data.get("username").rstrip().lower()
            my_first_name = data.get("firstName").rstrip()
            my_last_name = data.get("lastName").rstrip()
            my_email = data.get("email").rstrip()
            my_phone = data.get("phone").rstrip()
            my_password = data.get("password").rstrip()

            return User(my_user, my_first_name, my_last_name, my_email, my_password, my_phone)

        except KeyError:
            return None

        except IndexError:
            return None

    @staticmethod
    def from_json_username(data: dict) -> None:
        """From JSON to user.

        Args: 
            data: input JSON.
        """
        try:
            my_username = data.get("username").rstrip()
            user = User.query.filter(User.username == my_username).first()

            if user is None:
                raise NotFound("Username does not exist")
        
            return user  
        except KeyError:
            return None

        except IndexError:
            return None

    def update_json(self, data: dict) -> None:
        """Update a user from JSON.

        Args: 
            data: input JSON.
        """
        try:
            self.user_name = data.get("username").rstrip().lower()
            self.first_name = data.get("firstName").rstrip().lower()
            self.last_name = data.get("lastName").rstrip().lower()
            self.email = data.get("email").rstrip().lower()
            self.phone = data.get("phone").rstrip().lower()

        except:
            pass
