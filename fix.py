content = open('bot/main.py', encoding='utf-8').read()

old = """        db_user = get_user_by_telegram_id(db, user.id)
    if db_user and db_user.is_teacher:
        await cmd_start_teacher(update, context)
    elif db_user and db_user.is_student:
        await cmd_start_student(update, context)"""

new = """        db_user = get_user_by_telegram_id(db, user.id)
        role = db_user.role if db_user else None
    if role == "teacher":
        await cmd_start_teacher(update, context)
    elif role == "student":
        await cmd_start_student(update, context)"""

if old in content:
    open('bot/main.py', 'w', encoding='utf-8').write(content.replace(old, new))
    print('Fixed!')
else:
    print('NOT FOUND')