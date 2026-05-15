import os
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
from models import db, Product, Category, ProductImage

#база данных и само приложения
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///market.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
db.init_app(app)


@app.route('/')
def index():
    category_id = request.args.get('category_id', type=int)

    # Класическая фильтрация
    if category_id:
        products = Product.query.filter_by(category_id=category_id).all()
    else:
        products = Product.query.all()

    categories = Category.query.all()
    return render_template('index.html', products=products, categories=categories)


@app.route('/add', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        # Создаем товар
        new_product = Product(
            title=request.form['title'],
            description=request.form['description'],
            price=request.form['price'],
            contact_link=request.form['contact'],
            category_id=request.form['category']
        )
        db.session.add(new_product)
        db.session.flush()  # Получаем ID товара до коммита

        # Обработка нескольких фото
        files = request.files.getlist('photos')
        for file in files:
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                img = ProductImage(filename=filename, product_id=new_product.id)
                db.session.add(img)

        db.session.commit()
        return redirect(url_for('index'))

    categories = Category.query.all()
    return render_template('add_product.html', categories=categories)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Добавим категории для теста, если их нет
        if not Category.query.first():
            db.session.add_all([Category(name="Учебники"), Category(name="Техника"), Category(name="Спорт")])
            db.session.commit()
    app.run(debug=True)