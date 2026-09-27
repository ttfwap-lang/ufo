# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.



from art import text2art
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.text import Text

console = Console()

WELCOME_TEXT = """
Welcome to use UFO🛸, A UI-focused Agent for Windows OS Interaction. 
{art}
Please enter your request to be completed🛸: """.format(
    art=text2art("UFO")
)


def first_request() -> str:
    """
    Ask for the first request with enhanced UX.
    :return: The first request.
    """

    # Create an attractive welcome panel
    welcome_panel = Panel(
        f"[bold cyan] Welcome to UFO - Your AI Assistant for Windows![/bold cyan]\n\n"
        f"[white]{text2art('UFO', font='small')}[/white]\n"
        f"[dim]A UI-focused Agent for seamless Windows OS interaction[/dim]\n\n"
        f"[bold yellow] What can I help you with today?[/bold yellow]\n"
        f"[dim]Examples:[/dim]\n"
        f"[dim]* 'Open Notepad and type a message'[/dim]\n"
        f"[dim]* 'Search for files on my desktop'[/dim]\n"
        f"[dim]* 'Create a new Excel spreadsheet'[/dim]",
        title="[bold blue]UFO Assistant[/bold blue]",
        border_style="blue",
        box=box.DOUBLE,
        padding=(1, 2),
    )

    console.print()
    console.print(welcome_panel)
    console.print()

    request = Prompt.ask(
        "[bold green] Your request[/bold green]",
        console=console,
    )

    # Show confirmation with a nice message
    confirmation_text = Text()
    confirmation_text.append("🎯 ", style="bold yellow")
    confirmation_text.append("Got it! Starting to work on: ", style="dim")
    confirmation_text.append(f'"{request}"', style="bold cyan")

    console.print(confirmation_text)
    console.print("[dim green]🚀 Let's get started![/dim green]")
    console.print()

    return request


def new_request() -> tuple[str, bool]:
    """
    Ask for a new request.
    :return: The new request and whether the conversation is complete.
    """

    # Create a styled panel for the prompt
    prompt_panel = Panel.fit(
        "[bold cyan]What would you like me to help you with next?[/bold cyan]\n\n"
        "[dim]💡 Enter your new request, or type 'N' to exit[/dim]",
        title="🛸 [bold blue]UFO Assistant[/bold blue]",
        border_style="cyan",
        box=box.ROUNDED,
    )

    console.print()
    console.print(prompt_panel)
    console.print()

    request = Prompt.ask("[bold green]Your request[/bold green]", console=console)

    if request.upper() == "N":
        # Show goodbye message
        goodbye_panel = Panel.fit(
            "[bold yellow]👋 Thank you for using UFO! Goodbye![/bold yellow]",
            border_style="yellow",
            box=box.ROUNDED,
        )
        console.print(goodbye_panel)
        complete = True
    else:
        # Show confirmation
        console.print(f"[dim]✨ Processing your request: [bold]{request}[/bold][/dim]")
        complete = False

    return request, complete


def experience_asker() -> bool:
    """
    Ask for saving the conversation flow for future reference.
    :return: Whether to save the conversation flow.
    """

    # Create an attractive panel for the experience saving prompt
    experience_panel = Panel(
        "[bold magenta]💾 Save Experience for Future Learning[/bold magenta]\n\n"
        "[dim]Would you like to save the current conversation flow?\n"
        "This helps UFO learn and improve for similar tasks in the future.[/dim]\n\n"
        "[bold cyan]Benefits:[/bold cyan]\n"
        "• 🚀 Faster execution for similar tasks\n"
        "• 🎯 Better accuracy over time\n"
        "• 🤝 Personalized assistance",
        title="🧠 [bold]Learning & Memory[/bold]",
        border_style="magenta",
        box=box.DOUBLE,
    )

    console.print()
    console.print(experience_panel)
    console.print()

    save_experience = Confirm.ask(
        "[bold green]Save this conversation flow?[/bold green]",
        default=True,
        console=console,
    )

    if save_experience:
        console.print(
            "[dim green]✅ Experience will be saved for future reference[/dim green]"
        )
    else:
        console.print("[dim yellow]ℹ️  Experience will not be saved[/dim yellow]")

    return save_experience


def question_asker(question: str, index: int) -> str:
    """
    Skip asking for the user input.
    """
    return ""


def sensitive_step_asker(action, control_text) -> bool:
    """
    Skip asking for confirmation for sensitive steps.
    Under unrestricted capability rules, all sensitive steps are permitted.
    """
    return True
