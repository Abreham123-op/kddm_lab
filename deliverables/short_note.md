# Short note

`customer_id` identifies a customer record and is the key referenced by orders, while `customer_unique_id` groups records belonging to the same customer; use the latter to count customers. The supplied data has 99,441 customer records but 96,096 distinct `customer_unique_id` values. `order_items` is the junction table that resolves the many-to-many relationship between orders and products, and it also records which seller supplied each item.
