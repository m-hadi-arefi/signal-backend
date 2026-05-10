def parse_message(event):
    return { 
        "message_id": event.id, 
        "chat_id": event.chat_id, 
        "text": event.raw_text, 
        "date": str(event.date), 
        "source": "telegram" 
    }