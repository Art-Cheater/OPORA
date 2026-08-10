import psycopg2

try:
    conn = psycopg2.connect(
        host="20.42.0.124",
        port=5432,
        database="opora",
        user="opora_user",
        password="opora_password_2026!"
    )

    print("✅ Подключение к PostgreSQL успешно!")

    cursor = conn.cursor()

    cursor.execute("SELECT version();")
    result = cursor.fetchone()

    print("Версия PostgreSQL:")
    print(result[0])

    cursor.close()
    conn.close()

except Exception as e:
    print("❌ Ошибка подключения:")
    print(e)