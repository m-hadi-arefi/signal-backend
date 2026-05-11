from signal.core.kafka_client import KafkaConsumer

def get_lag(consumer: KafkaConsumer):
    partitions = consumer.assignment()
    end_offsets = consumer.end_offsets(partitions)

    lag = 0
    for p in partitions:
        lag += end_offsets[p] - consumer.position(p)

    return lag




