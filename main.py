import time
import datetime
import psycopg2
import psycopg2.extras

from scally_client import ZMQClient

from utils import get_user_status
from sending_alerts import send_telegram_message

DB_NAME = 'user_activity'
DB_USER = 'user_activity'
DB_PASSWORD = '1213'
DB_HOST = 'localhost'
DB_PORT = '5432'

def get_actions_with_payments():
    """
    Функция коннектится к базе PostgreSQL и делает выборку:
    - track_id, plan, status из таблицы actions_action
    - status из связанной payment_payment
    - user_id (кастомное поле) из таблицы user_activity_user
    """
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        query = """
            SELECT 
                a.track_id,
                a.plan,
                a.status AS action_status,
                p.status AS payment_status,
                u.user_id AS custom_user_id
            FROM actions_action a
            LEFT JOIN payment_payment p ON a.payment_id = p.id
            LEFT JOIN users_user u ON a.user_id = u.id;
        """
        
        cur.execute(query)
        rows = cur.fetchall()
        
        scally_client = ZMQClient()
        
        for row in rows:
            payment_status = row['payment_status']
            action_status = row['action_status']
            track_id = row['track_id']
            
            if action_status == "active":
                start_date = datetime.datetime.today().replace(hour=0, minute=0).isoformat(timespec='milliseconds')
                daily_activity = scally_client.get_document(username=track_id, creation_date_start=start_date, status="online")
                online_events = daily_activity.get("documents")
                online_events.sort(key=lambda x: x['creation_date'])

                total_time_online = 0
                time_distribution = {}

                for i in range(len(online_events) - 1):
                    start_time = datetime.datetime.fromisoformat(online_events[i]['creation_date'])
                    end_time = datetime.datetime.fromisoformat(online_events[i + 1]['creation_date'])

                    # Убедимся, что разница времени корректна
                    if end_time > start_time and online_events[i + 1]['status'] == 'online':
                        session_time = (end_time - start_time).total_seconds()
                        total_time_online += session_time

                        # Считаем распределение по часам
                        hour = start_time.hour
                        time_distribution[hour] = time_distribution.get(hour, 0) + session_time

                # Нахождение часа, когда человек чаще всего был в сети
                if time_distribution:
                    most_active_hour = max(time_distribution, key=time_distribution.get)
                    most_active_hour_duration = time_distribution[most_active_hour]
                else:
                    most_active_hour = 0
                    most_active_hour_duration = 0

                # Перевод суммарного времени в удобный формат
                total_time_delta = datetime.timedelta(seconds=int(len(online_events)))
                hours, remainder = divmod(total_time_delta.seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                total = datetime.time(hour=hours, minute=minutes, second=seconds)
                most_active_hour = datetime.time(hour=most_active_hour)
                
                scally_client.upsert_daily_report(
                    username=track_id, 
                    most_active_hour=most_active_hour,
                    total=total
                    
                )


            
    except psycopg2.Error as e:
        print("Ошибка при работе с PostgreSQL:", e)
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

while True:
    get_actions_with_payments()
    time.sleep(1)
