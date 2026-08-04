from typer import Typer

app = Typer(
    no_args_is_help=True,
    rich_markup_mode="markdown",
)


@app.command()
def main():
    print("hello")


if __name__ == "__main__":
    app()
