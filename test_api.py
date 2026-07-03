from freelancehunt.client import FreelancehuntClient, FreelancehuntError


def main() -> None:
    client = FreelancehuntClient()

    try:
        profile = client.my_profile()
    except FreelancehuntError as e:
        print(f"Ошибка API: {e}")
        return

    data = profile["data"]
    attrs = data["attributes"]

    print(f"ID: {data['id']}")
    print(f"Тип: {data['type']}")
    print(f"Логин: {attrs.get('login')}")
    print(f"Имя: {attrs.get('first_name')} {attrs.get('last_name')}")
    print(f"Статус: {attrs.get('status', {}).get('name')}")


if __name__ == "__main__":
    main()
