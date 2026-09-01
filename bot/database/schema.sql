-- NOCTRA database schema. SQLite now; columns/types chosen to migrate
-- cleanly to Postgres/MySQL later (explicit TEXT timestamps, no SQLite-only
-- tricks beyond AUTOINCREMENT).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    emoji       TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Sits between Category and Product (Category -> Category Type -> Product).
-- Replaces the old per-product "variant" concept: instead of one product
-- having several priced sub-options, products are grouped under a type and
-- each product is its own fully independent, fully priced item.
CREATE TABLE IF NOT EXISTS category_types (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    emoji       TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    category_type_id  INTEGER NOT NULL REFERENCES category_types(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    description       TEXT,
    image_url         TEXT,
    emoji             TEXT,
    product_type      TEXT NOT NULL DEFAULT 'manual',     -- manual | automatic | digital | service
    stock_type        TEXT NOT NULL DEFAULT 'unlimited',  -- unlimited | manual
    stock_quantity    INTEGER NOT NULL DEFAULT 0,
    visible           INTEGER NOT NULL DEFAULT 1,
    base_price        REAL NOT NULL DEFAULT 0,
    currency_label    TEXT NOT NULL DEFAULT 'USD',
    discount_type     TEXT,                                -- NULL | percent | flat
    discount_value    REAL NOT NULL DEFAULT 0,
    position          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Dynamic checkout fields now live on the category TYPE, not the product --
-- every product under a type automatically shares the same set of fields,
-- so you configure them once per type instead of once per product.
CREATE TABLE IF NOT EXISTS product_fields (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    category_type_id  INTEGER NOT NULL REFERENCES category_types(id) ON DELETE CASCADE,
    label             TEXT NOT NULL,
    field_type        TEXT NOT NULL DEFAULT 'custom',  -- username|userid|login|email|password|serverid|gameid|custom
    required          INTEGER NOT NULL DEFAULT 1,
    placeholder       TEXT,
    min_length        INTEGER NOT NULL DEFAULT 0,
    max_length        INTEGER NOT NULL DEFAULT 100,
    validation        TEXT NOT NULL DEFAULT 'none',    -- none|numeric|alpha|alphanumeric|email
    position          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payment_methods (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    instructions     TEXT,
    image_url        TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1,
    timeout_minutes  INTEGER NOT NULL DEFAULT 30,
    position         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL,
    product_id          INTEGER NOT NULL REFERENCES products(id),
    payment_method_id   INTEGER REFERENCES payment_methods(id),
    unit_price          REAL NOT NULL,
    total_price         REAL NOT NULL,
    currency_label      TEXT NOT NULL DEFAULT 'USD',
    status              TEXT NOT NULL DEFAULT 'pending',   -- pending|processing|completed|cancelled|refunded
    payment_status      TEXT NOT NULL DEFAULT 'pending',   -- pending|paid|expired|cancelled
    stock_reserved      INTEGER NOT NULL DEFAULT 0,
    ticket_channel_id   INTEGER,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    payment_deadline    TEXT
);

CREATE TABLE IF NOT EXISTS order_field_values (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id  INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    label     TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'custom',
    value     TEXT
);

-- Messages NOCTRA sent in the customer's DM during checkout for this order
-- (order summary, payment instructions, etc.) -- tracked so they can be
-- cleaned up automatically once the order is marked completed, instead of
-- piling up in the customer's DM forever.
CREATE TABLE IF NOT EXISTS order_dm_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    channel_id  INTEGER NOT NULL,
    message_id  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id          INTEGER REFERENCES orders(id),
    user_id           INTEGER NOT NULL,
    channel_id        INTEGER NOT NULL UNIQUE,
    kind              TEXT NOT NULL DEFAULT 'order',   -- order | support
    status            TEXT NOT NULL DEFAULT 'open',    -- open | closed | archived
    close_reason      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at         TEXT,
    last_activity_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id             INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    product_id           INTEGER NOT NULL REFERENCES products(id),
    user_id              INTEGER NOT NULL,
    rating               INTEGER NOT NULL,
    review_text          TEXT,
    image_url            TEXT,
    anonymous            INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|hidden
    awaiting_photo       INTEGER NOT NULL DEFAULT 0,
    awaiting_photo_since TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);

-- Isi tombol "Reply" yang ditambahin lewat /panel atau /announcement --
-- beda sama tombol link (yang cuma nyimpen URL langsung di komponen
-- pesannya), tombol reply butuh nyimpen teks balasannya di sini biar bisa
-- dipanggil balik pas diklik, bahkan abis bot restart (custom_id-nya cuma
-- nyimpen ID row ini, bukan teksnya langsung).
CREATE TABLE IF NOT EXISTS panel_reply_buttons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,
    reply_text  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Kartu digital NOCTRA -- saldo Credit (dari deposit customer, dipake
-- checkout), Noctoins (didapet dari transaksi bayar pake Credit, bisa jadi
-- potongan harga), dan Server Points (statistik seberapa sering belanja
-- pake card, gak bisa di-redeem). card_id itu serial/referensi doang buat
-- kebutuhan support -- BUKAN kredensial: semua aksi (cek saldo, isi saldo)
-- selalu ke-tie ke akun Discord yang invoke, bukan berdasarkan ID yang
-- diketik siapapun (lihat bot.utils.card_actions).
CREATE TABLE IF NOT EXISTS cards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL UNIQUE,
    card_id         TEXT NOT NULL UNIQUE,
    credit_balance  REAL NOT NULL DEFAULT 0,
    noctoins        INTEGER NOT NULL DEFAULT 0,
    server_points   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Permintaan bikin kartu baru / isi saldo yang nunggu approve staff --
-- alurnya mirip bot.cogs.payment_proof (customer DM bukti transfer), tapi
-- kepisah total dari orders soalnya kartu bukan produk. Status:
-- awaiting_proof (modal disubmit, nunggu customer kirim screenshot) ->
-- pending (foto masuk, nunggu keputusan staff) -> approved | rejected.
CREATE TABLE IF NOT EXISTS card_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL,                    -- create | topup
    amount      REAL NOT NULL,
    admin_fee   REAL NOT NULL DEFAULT 0,           -- cuma keisi buat kind=create
    proof_url   TEXT,
    status      TEXT NOT NULL DEFAULT 'awaiting_proof',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);
