from flask import Blueprint, render_template, request, jsonify
from .utils import create_url
from datetime import datetime

main_routes = Blueprint('main_routes', __name__)


class InvalidData(Exception):
    """
    An error describes invalid input data
    """
    def __init__(self, error_code, error_message, details=""):
        self.code = error_code
        self.message = error_message
        self.details = details


@main_routes.errorhandler(InvalidData)
def handle_invalid_data(error):
    response = jsonify({"error": {
            "message": error.message,
            "details": error.details,
        }
    })
    response.status_code = error.code
    return response


@main_routes.route('/', methods=['GET'])
def get_main_page():
    return render_template('editor.html')


@main_routes.route('/save', methods=['POST'])
def save():
    data = request.get_json()

    datetime_user = data.get('date')
    if not datetime_user:
        raise InvalidData(400, "Некорректная дата")

    try:
        datetime_user = datetime.strptime(datetime_user, "%Y-%m-%dT%H:%M")
    except (ValueError, TypeError) as e:
        raise InvalidData(400, "Некорректный формат даты",
                          "Ожидается формат даты: %Y-%m-%dT%H:%M")

    if datetime_user < datetime.now():
        raise InvalidData(400, "Некорректное время жизни поста")

    url = create_url()
    text_user = data.get('text')

    # TODO: save post to DB

    return jsonify({'message': "Пост успешно сохранен",
                    'code': 200,
                    'link': url,
                    }), 200




