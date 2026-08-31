import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from app.models.catalog import (
    CartRequest, CartResponse, CheckoutRequest, CheckoutResponse,
    LoginRequest, LoginResponse, Product
)

router = APIRouter(tags=["E-Commerce API"])

# In-memory realistic product catalog
SAMPLE_PRODUCTS: List[Product] = [
    Product(id="prod-001", name="Ultra-Shield Cloud WAF", category="security", price=299.99, inventory=150, description="Enterprise edge security layer."),
    Product(id="prod-002", name="Neural Scale Pod", category="compute", price=49.99, inventory=500, description="Auto-optimizing container pod allocation."),
    Product(id="prod-003", name="TraceIQ Observability Agent", category="telemetry", price=89.50, inventory=250, description="Distributed tracing and span analytics."),
    Product(id="prod-004", name="RateGuard Rate Limiter", category="security", price=120.00, inventory=80, description="Token-bucket rate limiter with IP reputation."),
    Product(id="prod-005", name="KubeBalance Service Mesh", category="networking", price=199.00, inventory=120, description="Traffic routing and mTLS infrastructure."),
]


@router.get("/products", response_model=List[Product])
async def list_products(
    category: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=50)
):
    """Retrieve catalog of products."""
    products = SAMPLE_PRODUCTS
    if category:
        products = [p for p in products if p.category.lower() == category.lower()]
    return products[:limit]


@router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str):
    """Retrieve single product by ID."""
    for p in SAMPLE_PRODUCTS:
        if p.id == product_id:
            return p
    raise HTTPException(status_code=404, detail="Product not found")


@router.get("/search", response_model=List[Product])
async def search_products(q: str = Query(..., min_length=1)):
    """Search products by keyword."""
    query = q.lower()
    return [p for p in SAMPLE_PRODUCTS if query in p.name.lower() or query in p.description.lower()]


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Simulate user authentication."""
    if not request.username or not request.password:
        raise HTTPException(status_code=400, detail="Username and password required")
    return LoginResponse(
        token=f"jwt-mock-{uuid.uuid4().hex}",
        user_id=f"user-{request.username}",
        expires_in_seconds=3600
    )


@router.post("/cart", response_model=CartResponse)
async def update_cart(request: CartRequest):
    """Add items to user cart."""
    product_map = {p.id: p.price for p in SAMPLE_PRODUCTS}
    total = sum(product_map.get(item.product_id, 50.0) * item.quantity for item in request.items)
    return CartResponse(
        cart_id=f"cart-{uuid.uuid4().hex[:8]}",
        user_id=request.user_id,
        items=request.items,
        total_amount=round(total, 2)
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(request: CheckoutRequest):
    """Process shopping cart checkout."""
    return CheckoutResponse(
        order_id=f"order-{uuid.uuid4().hex[:10]}",
        cart_id=request.cart_id,
        status="completed",
        charged_amount=349.98,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
