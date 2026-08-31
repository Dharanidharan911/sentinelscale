from typing import List, Optional
from pydantic import BaseModel, Field


class Product(BaseModel):
    id: str
    name: str
    category: str
    price: float
    inventory: int
    description: str


class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(default=1, ge=1)


class CartRequest(BaseModel):
    user_id: str
    items: List[CartItem]


class CartResponse(BaseModel):
    cart_id: str
    user_id: str
    items: List[CartItem]
    total_amount: float


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    user_id: str
    expires_in_seconds: int = 3600


class CheckoutRequest(BaseModel):
    cart_id: str
    payment_method: str = "credit_card"
    shipping_address: str


class CheckoutResponse(BaseModel):
    order_id: str
    cart_id: str
    status: str
    charged_amount: float
    timestamp: str
