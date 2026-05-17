import os
import logging
from doctest import debug

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Product, Category, ProductImage

# ==========================================
# НАСТРОЙКА ЛОГИРОВАНИЯ (ДЛЯ АДМИНИСТРИРОВАНИЯ)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),  # Вывод логов в консоль (удобно для Amvera)
        logging.FileHandler("app_system.log", encoding='utf-8')  # Дублирование в файл
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_123'  # Нужно для работы сессий
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///market.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.json.ensure_ascii = False

db.init_app(app)

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.template_filter('format_price')
def format_price(value):
    if value is None:
        return "0"
    try:
        # Форматируем число с разделением тысяч запятыми (1,000,000),
        # а затем заменяем запятые на красивые пробелы (1 000 000)
        return "{:,}".format(int(value)).replace(",", " ")
    except (ValueError, TypeError):
        return value


# ==========================================
# КАСТОМНЫЕ ОБРАБОТЧИКИ ОШИБОК
# ==========================================
@app.errorhandler(404)
def page_not_found(e):
    logger.warning(f"Ошибка 404: Запрошена несуществующая страница -> {request.url}")
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"Ошибка 500: Внутренняя ошибка сервера -> {request.url}")
    db.session.rollback()  # Откатываем сессию БД, если транзакция сломалась
    return render_template('500.html'), 500


# --- МАРШРУТЫ АВТОРИЗАЦИИ ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        # Валидация
        if len(username) < 3:
            flash('Логин должен содержать минимум 3 символа.', 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash('Пароль должен быть не короче 6 символов.', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким логином уже существует.', 'danger')
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()

        logger.info(f"Зарегистрирован новый пользователь: {username}")
        flash('Регистрация прошла успешно! Теперь вы можете войти.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            logger.info(f"Пользователь {username} вошел в систему.")
            return redirect(url_for('index'))

        logger.warning(f"Неудачная попытка входа для логина: {username}")
        flash('Неверный логин или пароль.', 'danger')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logger.info(f"Пользователь {current_user.username} вышел из системы.")
    logout_user()
    return redirect(url_for('index'))


# --- ОСНОВНОЙ ФУНКЦИОНАЛ ---

# ==========================================
# 1. ГЛАВНАЯ СТРАНИЦА И ПОИСК
# ==========================================
@app.route('/')
def index():
    category_id = request.args.get('category_id')
    search_query = request.args.get('search')
    max_price = request.args.get('max_price')
    sort_by = request.args.get('sort_by', 'new')  # По умолчанию сначала новые

    # 1) ПОЛУЧАЕМ НОМЕР СТРАНИЦЫ
    page = request.args.get('page', 1, type=int)

    query = Product.query

    # Фильтры
    if category_id:
        query = query.filter_by(category_id=category_id)
    if search_query:
        query = query.filter(Product.title.ilike(f'%{search_query}%'))
    if max_price and max_price.isdigit():
        query = query.filter(Product.price <= int(max_price))

    # Сортировка (расширенная)
    if sort_by == 'price_asc':
        query = query.order_by(Product.price.asc())
    elif sort_by == 'price_desc':
        query = query.order_by(Product.price.desc())
    elif sort_by == 'views':
        query = query.order_by(Product.views.desc())
    elif sort_by == 'title_asc':
        query = query.order_by(Product.title.asc())
    elif sort_by == 'title_desc':
        query = query.order_by(Product.title.desc())
    else:  # 'new'
        query = query.order_by(Product.created_at.desc())

    # 2) ПРИМЕНЯЕМ ПАГИНАЦИЮ
    pagination = query.paginate(page=page, per_page=8, error_out=False)

    products = pagination.items
    categories = Category.query.all()

    user_favorite_ids = []
    if current_user.is_authenticated:
        user_favorite_ids = [p.id for p in current_user.favorite_products]

    return render_template(
        'index.html',
        products=products,
        categories=categories,
        user_favorite_ids=user_favorite_ids,
        pagination=pagination
    )


# ==========================================
# 5. ЛИЧНЫЙ КАБИНЕТ (ПРОФИЛЬ)
# ==========================================
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')

        if len(new_password) < 6:
            flash('Новый пароль должен быть не короче 6 символов.', 'warning')
            return redirect(url_for('profile'))

        if check_password_hash(current_user.password_hash, old_password):
            current_user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            logger.info(f"Пользователь {current_user.username} успешно изменил пароль.")
            flash('Пароль успешно изменен!', 'success')
        else:
            logger.warning(f"Неудачная попытка смены пароля для пользователя {current_user.username}.")
            flash('Неверный текущий пароль.', 'danger')
        return redirect(url_for('profile'))

    user_products = Product.query.filter_by(user_id=current_user.id).order_by(Product.id.desc()).all()
    favorite_products = current_user.favorite_products

    return render_template('profile.html', products=user_products, favorite_products=favorite_products)


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)

    if product.views is None:
        product.views = 0

    if 'viewed_products' not in session:
        session['viewed_products'] = []

    viewed = list(session['viewed_products'])

    if product_id not in viewed:
        product.views += 1
        viewed.append(product_id)
        session['viewed_products'] = viewed
        session.modified = True
        db.session.commit()

    user_favorite_ids = []
    if current_user.is_authenticated:
        user_favorite_ids = [p.id for p in current_user.favorite_products]

    return render_template('product_detail.html', product=product, user_favorite_ids=user_favorite_ids)


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        price = request.form.get('price')
        description = request.form.get('description', '').strip()
        contact = request.form.get('contact', '').strip()
        category_id = request.form.get('category')

        # ----------------------------------------
        # БЛОК ВАЛИДАЦИИ ФОРМЫ (Возвращаем values=request.form)
        # ----------------------------------------
        if len(title) < 5:
            flash('Название объявления должно содержать минимум 5 символов.', 'danger')
            return render_template('add_product.html', categories=Category.query.all(), values=request.form)

        if len(description) < 10:
            flash('Описание слишком короткое. Напишите хотя бы пару слов о товаре.', 'danger')
            return render_template('add_product.html', categories=Category.query.all(), values=request.form)

        try:
            price_val = float(price)
            if price_val < 0 or price_val > 1000000:
                flash('Указана некорректная цена (допускается от 0 до 1 000 000 ₽).', 'danger')
                return render_template('add_product.html', categories=Category.query.all(), values=request.form)
        except (ValueError, TypeError):
            flash('Цена должна быть числом.', 'danger')
            return render_template('add_product.html', categories=Category.query.all(), values=request.form)

        new_product = Product(
            title=title,
            description=description,
            price=price_val,
            contact_link=contact,
            category_id=category_id,
            user_id=current_user.id
        )
        db.session.add(new_product)
        db.session.flush()

        files = request.files.getlist('photos')
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db.session.add(ProductImage(filename=filename, product_id=new_product.id))

        db.session.commit()

        logger.info(f"Пользователь {current_user.username} создал новое объявление: ID {new_product.id}")

        if 'viewed_products' not in session:
            session['viewed_products'] = []
        viewed = list(session['viewed_products'])
        viewed.append(new_product.id)
        session['viewed_products'] = viewed
        session.modified = True

        return redirect(url_for('product_detail', product_id=new_product.id))

    return render_template('add_product.html', categories=Category.query.all())


@app.route('/favorite/toggle/<int:product_id>')
@login_required
def toggle_favorite(product_id):
    product = Product.query.get_or_404(product_id)
    session.pop('_flashes', None)

    if product in current_user.favorite_products:
        current_user.favorite_products.remove(product)
        flash('Удалено из избранного', 'info')
    else:
        current_user.favorite_products.append(product)
        flash('Добавлено в избранное!', 'success')

    db.session.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/api/products', methods=['GET'])
def get_products_api():
    products = Product.query.all()
    output = []
    for p in products:
        p_data = {
            'id': p.id,
            'title': p.title,
            'price': p.price,
            'description': p.description,
            'category': p.category.name,
            'seller': p.seller.username,
            'images': [url_for('static', filename='uploads/' + img.filename, _external=True) for img in p.images]
        }
        output.append(p_data)
    return jsonify({'products': output})


# ==========================================
# 4. РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ ОБЪЯВЛЕНИЙ
# ==========================================

@app.route('/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)

    if product.user_id != current_user.id:
        logger.warning(
            f"Попытка несанкционированного редактирования! Юзер {current_user.username} пытался изменить товар {product_id}")
        flash('Вы не можете редактировать чужие объявления!', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        price = request.form.get('price')

        # Строгая валидация при обновлении (Возвращаем значения обратно)
        if len(title) < 5:
            flash('Название объявления должно содержать минимум 5 символов.', 'danger')
            return render_template('edit_product.html', product=product, categories=Category.query.all(), values=request.form)

        try:
            price_val = float(price)
            if price_val < 0 or price_val > 1000000:
                flash('Указана некорректная цена (допускается от 0 до 1 000 000 ₽).', 'danger')
                return render_template('edit_product.html', product=product, categories=Category.query.all(), values=request.form)
        except (ValueError, TypeError):
            flash('Цена должна быть числом.', 'danger')
            return render_template('edit_product.html', product=product, categories=Category.query.all(), values=request.form)

        # 1. Сначала обрабатываем УДАЛЕНИЕ выбранных фотографий
        delete_images_ids = request.form.getlist('delete_images')
        if delete_images_ids:
            for img_id in delete_images_ids:
                image_to_del = ProductImage.query.get(int(img_id))
                if image_to_del and image_to_del.product_id == product.id:
                    try:
                        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], image_to_del.filename))
                    except FileNotFoundError:
                        pass
                    db.session.delete(image_to_del)

        # 2. Обновляем основные текстовые поля
        product.title = title
        product.category_id = request.form.get('category')
        product.price = price_val
        product.description = request.form.get('description')
        product.contact_link = request.form.get('contact')

        # 3. Обрабатываем ДОБАВЛЕНИЕ новых фото
        files = request.files.getlist('photos')
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db.session.add(ProductImage(filename=filename, product_id=product.id))

        db.session.commit()
        logger.info(f"Объявление {product.id} было отредактировано пользователем {current_user.username}")
        flash('Объявление успешно обновлено!', 'success')
        return redirect(url_for('index'))

    categories = Category.query.all()
    return render_template('edit_product.html', product=product, categories=categories)


@app.route('/delete/<int:product_id>', methods=['POST', 'GET'])
@login_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)

    if product.user_id != current_user.id:
        logger.warning(f"Нарушение прав доступа! Юзер {current_user.username} пытался удалить товар {product_id}")
        flash('Вы не можете удалить чужое объявление!', 'danger')
        return redirect(url_for('index'))

    for img in product.images:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], img.filename))
        except FileNotFoundError:
            pass
        db.session.delete(img)

    db.session.delete(product)
    db.session.commit()

    logger.info(f"Объявление {product_id} успешно удалено пользователем {current_user.username}")
    flash('Объявление успешно удалено.', 'success')
    return redirect(url_for('index'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not Category.query.first():
            db.session.add_all([Category(name="Учебники"), Category(name="Техника"), Category(name="Спорт")])
            db.session.commit()
    env_port = os.environ.get("PORT")

    if not env_port or env_port == '':
        server_port = 80
    else:
        server_port = int(env_port)

    logger.info(f"Сервер запускается на порту {server_port}")
    #app.run(host='0.0.0.0', port=server_port)
    app.run(debug=True)