# fulfiliq_test_model.py
# In-memory Python test model for the Omnichannel Order Fulfilment Platform (Assignment 2)
# Demonstrates rule logic and critical behaviour validation scenarios (T1-T7)

import datetime

class FulfilIQSystem:
    def __init__(self):
        # Synthetic data stores
        self.stock = {}
        self.orders = {}
        self.payments = set()
        self.intents = {}
        self.refunds = {}

    def setup_stock(self, sku, quantity):
        self.stock[sku] = {"on_hand": quantity, "reserved": 0}

    def place_order(self, user_id, order_id, sku, qty, current_time):
        item = self.stock.get(sku)
        if not item:
            raise ValueError("Item not found")
        
        if item["on_hand"] - item["reserved"] >= qty:
            item["reserved"] += qty
            self.orders[order_id] = {
                "owner_id": user_id,
                "sku": sku,
                "qty": qty,
                "state": "Placed",
                "expires_at": current_time + datetime.timedelta(minutes=15)
            }
            return True
        return False

    def confirm_payment(self, gateway_id, event_id, order_id, current_time):
        event_key = f"{gateway_id}_{event_id}"
        if event_key in self.payments:
            return "Duplicate callback ignored"
        
        self.payments.add(event_key)
        order = self.orders.get(order_id)
        if not order:
            raise ValueError("Order not found")

        # Handle T7: Late payment after reservation expiry
        if current_time > order["expires_at"]:
            order["state"] = "Payment Received, Needs Refund"
            # Trigger refund flow...
            self.refunds[order_id] = {"state": "Requested", "amount": 100, "approved_by": None}
            return "Late payment - Refund required"

        order["state"] = "Paid"
        self.intents[order_id] = {"status": "Pending", "correlation_key": f"sync_{order_id}", "attempts": 0}
        return "Payment confirmed"

    def dispatch_order(self, user_role, order_id):
        if user_role not in ["Picker", "Admin"]:
            raise PermissionError("Unauthorized to dispatch")
            
        order = self.orders.get(order_id)
        if order["state"] != "Paid" and order["state"] != "Packed":
            raise ValueError(f"Cannot dispatch order in state: {order['state']}")
            
        order["state"] = "Dispatched"
        return "Dispatched successfully"

    def expire_reservations(self, current_time):
        for o_id, order in self.orders.items():
            if order["state"] == "Placed" and current_time > order["expires_at"]:
                order["state"] = "Cancelled"
                sku = order["sku"]
                self.stock[sku]["reserved"] -= order["qty"]

    def request_refund(self, user_role, order_id, amount):
        if user_role not in ["Support Agent", "Admin"]:
            raise PermissionError("Unauthorized to request refund")
        self.refunds[order_id] = {"state": "Requested", "amount": amount, "approved_by": None}
        return "Refund requested"

    def approve_refund(self, user_role, order_id):
        if user_role != "Finance Reviewer":
            raise PermissionError("Only Finance Reviewer can approve refunds")
        refund = self.refunds.get(order_id)
        if refund:
            refund["state"] = "Approved"
            refund["approved_by"] = user_role
            return "Refund approved"
        raise ValueError("Refund not found")

    def execute_refund(self, order_id, gateway_success):
        refund = self.refunds.get(order_id)
        if refund["state"] != "Approved" and refund["state"] != "Failed":
            raise ValueError("Refund must be approved before execution")
        
        if gateway_success:
            refund["state"] = "Executed"
            self.orders[order_id]["state"] = "Closed"
            return "Refund executed"
        else:
            refund["state"] = "Failed" # Approval is kept for retry
            return "Gateway failed, marked for retry"

    def sync_courier(self, order_id, success, timeout):
        intent = self.intents.get(order_id)
        intent["attempts"] += 1
        if timeout or not success:
            return f"Sync failed on attempt {intent['attempts']}, intent remains {intent['status']} with key {intent['correlation_key']}"
        intent["status"] = "Completed"
        return "Sync successful"

    def read_order(self, user_id, user_role, target_order_id):
        order = self.orders.get(target_order_id)
        if user_role == "Customer" and order["owner_id"] != user_id:
            raise PermissionError("Cross-customer read rejected at API boundary")
        return order


# --- Test Scenarios ---
def run_tests():
    sys = FulfilIQSystem()
    base_time = datetime.datetime(2026, 1, 1, 12, 0, 0)
    
    print("Running Validation Scenarios...")
    
    # T1: Two buyers, last unit
    sys.setup_stock("SKU-1", 1)
    res1 = sys.place_order("UserA", "ORD-1", "SKU-1", 1, base_time)
    res2 = sys.place_order("UserB", "ORD-2", "SKU-1", 1, base_time)
    print(f"T1 (Two buyers, last unit): Buyer 1 Success={res1}, Buyer 2 Success={res2}")
    
    # T2: Duplicate callback
    sys.confirm_payment("GW1", "EVT-99", "ORD-1", base_time)
    res_dup = sys.confirm_payment("GW1", "EVT-99", "ORD-1", base_time)
    print(f"T2 (Duplicate callback): Second attempt result='{res_dup}'")
    
    # T3: Approved refund fails at gateway
    sys.request_refund("Support Agent", "ORD-1", 50)
    sys.approve_refund("Finance Reviewer", "ORD-1")
    fail_res = sys.execute_refund("ORD-1", gateway_success=False)
    state_after_fail = sys.refunds["ORD-1"]["state"]
    print(f"T3 (Refund fails): Result='{fail_res}', Current State='{state_after_fail}' (Prior approval kept)")
    
    # T4: Dispatch without payment
    sys.setup_stock("SKU-2", 10)
    sys.place_order("UserC", "ORD-3", "SKU-2", 1, base_time)
    try:
        sys.dispatch_order("Picker", "ORD-3")
    except Exception as e:
        print(f"T4 (Dispatch without payment): Rejected with error -> {str(e)}")
        
    # T5: Courier timeout then retry
    sync_res_1 = sys.sync_courier("ORD-1", success=False, timeout=True)
    intent = sys.intents["ORD-1"]
    print(f"T5 (Courier timeout): {sync_res_1}")
    
    # T6: Customer or agent approves refund; cross-customer read
    try:
        sys.approve_refund("Customer", "ORD-1")
    except Exception as e:
        print(f"T6 (Unauthorized approve): Rejected -> {str(e)}")
        
    try:
        sys.read_order("UserB", "Customer", "ORD-1") # UserB trying to read UserA's order
    except Exception as e:
        print(f"T6 (Cross-customer read): Rejected -> {str(e)}")

    # T7: Late payment after reservation expiry
    sys.setup_stock("SKU-3", 1)
    sys.place_order("UserD", "ORD-4", "SKU-3", 1, base_time)
    late_time = base_time + datetime.timedelta(minutes=20)
    sys.expire_reservations(late_time)
    late_res = sys.confirm_payment("GW2", "EVT-100", "ORD-4", late_time)
    print(f"T7 (Late payment): Result='{late_res}', Order State='{sys.orders['ORD-4']['state']}'")

if __name__ == '__main__':
    run_tests()
