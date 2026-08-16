"""Demo file to verify the CI review workflow blocks merges on high-severity issues."""


def evaluate_expression(expression):
    return eval(expression)


def load_data(payload):
    import pickle

    return pickle.loads(payload)


def fetch_config(key):
    settings = {"debug": True}
    return settings[key]


def run():
    result = evaluate_expression("2 + 2")
    data = load_data(b"")
    print(result, data)


if __name__ == "__main__":
    run()
