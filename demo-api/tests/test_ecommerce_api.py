from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_list_products():
    response = client.get("/products")
    assert response.status_code == 200
    products = response.json()
    assert len(products) > 0
    assert "id" in products[0]
    assert "name" in products[0]


def test_get_product_by_id():
    response = client.get("/products/prod-001")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "prod-001"
    assert "price" in data


def test_get_product_not_found():
    response = client.get("/products/prod-non-existent")
    assert response.status_code == 404


def test_search_products():
    response = client.get("/search?q=scale")
    assert response.status_code == 200
    results = response.json()
    assert len(results) >= 1


def test_login():
    response = client.post("/login", json={"username": "alice", "password": "securepassword"})
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["user_id"] == "user-alice"


def test_cart_and_checkout():
    # 1. Update Cart
    cart_payload = {
        "user_id": "user-alice",
        "items": [
            {"product_id": "prod-001", "quantity": 1},
            {"product_id": "prod-002", "quantity": 2}
        ]
    }
    cart_res = client.post("/cart", json=cart_payload)
    assert cart_res.status_code == 200
    cart_data = cart_res.json()
    assert "cart_id" in cart_data
    assert cart_data["total_amount"] > 0

    # 2. Checkout
    checkout_payload = {
        "cart_id": cart_data["cart_id"],
        "payment_method": "credit_card",
        "shipping_address": "123 Cloud Way"
    }
    checkout_res = client.post("/checkout", json=checkout_payload)
    assert checkout_res.status_code == 200
    checkout_data = checkout_res.json()
    assert checkout_data["status"] == "completed"
    assert "order_id" in checkout_data
