from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

# Промежуточная таблица Many-to-Many для Избранного
# Связывает ID пользователя и ID товара
favorites = db.Table('favorites',
                     db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
                     db.Column('product_id', db.Integer, db.ForeignKey('product.id'), primary_key=True)
                     )


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    # Связь: объявления, которые создал этот пользователь
    products = db.relationship('Product', backref='seller', lazy=True)

    # Связь Many-to-Many: товары, которые пользователь добавил в избранное
    favorite_products = db.relationship('Product', secondary=favorites,
                                        backref=db.backref('favorited_by', lazy='dynamic'))


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Integer, nullable=False)
    contact_link = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)

    # НОВЫЕ ПОЛЯ:
    created_at = db.Column(db.DateTime, default=datetime.now)  # Дата публикации
    views = db.Column(db.Integer, default=0)  # Счетчик просмотров

    # Отношения
    images = db.relationship('ProductImage', backref='product', cascade="all, delete-orphan", lazy=True)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    products = db.relationship('Product', backref='category', lazy=True)


class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)