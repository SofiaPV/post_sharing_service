import json

from flask import Blueprint, render_template, request, jsonify
from app.utilis.url_generator import create_url
from datetime import datetime, timezone
from dateutil.parser import isoparse

from app.utilis.celery.tasks import save_post, get_post
from app.utilis.logger import logger

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

    # datetime checking
    datetime_user = data.get('date')
    if not datetime_user:
        raise InvalidData(400, "Некорректная дата")

    try:
        datetime_user = isoparse(datetime_user)
    except (ValueError, TypeError) as e:
        raise InvalidData(400, "Некорректный формат даты")

    if datetime_user.tzinfo is None:
        raise InvalidData(400, "Время должно содержать информацию о часовом поясе")

    datetime_user = datetime_user.astimezone(timezone.utc)
    if datetime_user < datetime.now(timezone.utc):
        raise InvalidData(400, "Некорректное время жизни поста")

    # data checking
    text_user = data.get('text')
    if not text_user or not isinstance(text_user, dict):
        raise InvalidData(400, "Пост пустой или не в формате dict (json)")

    # url creation
    url = create_url()

    # adding to database using celery queue
    success = save_post.apply_async(args=[url, datetime_user, text_user])
    logger.info(f"routes.py: save: {success}")

    return jsonify({'message': "Пост ожидает сохранения",
                    'code': 200,
                    'link': url,
                    }), 200


@main_routes.route('/post/<string:url>', methods=['GET'])
def get_post_main(url):
    task = get_post.apply_async(args=[url])  # gets Post
    response = None
    try:
        response = task.get()  # TODO: undertand...
    except Exception as e:
        logger.error(f"routes.py: get_post_main(): {e}", exc_info=True)

    def form_response(text: str):
        return {'blocks': [
                    {
                        "id": "1",
                        "type": "paragraph",
                        "data": {
                             "text": text
                    }}
                ]}

    if response is None:
        return jsonify({
            'message': 'Пост не найден',
            'code': 404,
            'link': url
        }), 404

    data = response["data"]
    logger.info(f"routes.py: get_post_main(): {data=}")
    if data is None:
        if response.status == "pending":
            data = form_response("Статья ожидает сохранения. Возвращайтесь позже!")
        else:
            data = form_response("Произошла ошибка, статью не удалось сохранить :(")

    return render_template("post_viewer.html", content=json.dumps(data))
