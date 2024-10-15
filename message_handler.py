class MessageHandler:

    MAX_CHARS = 1900
    SPLIT_POINT = 1500

    def __init__(self, message):
        self.response = []
        if len(message) < 2000:
            # just send it if we can
            self.response.append(message)
        else:
            self.response.extend(self.handle_large_messages(message))

    def handle_large_messages(self, message):
        if len(message) / self.MAX_CHARS > 1:
            split_point = self.SPLIT_POINT
            for char in message[self.SPLIT_POINT:]:
                if char != '\n':
                    split_point += 1
                else:
                    break
            broken_up_response = [message[:split_point], message[split_point:]]
        else:
            broken_up_response = [message]
        return broken_up_response
