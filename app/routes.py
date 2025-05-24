from flask import Blueprint, render_template

main_routes = Blueprint('main_routes', __name__)


@main_routes.route('/', methods=['GET'])
def get_main_page():
    return render_template('editor.html')

