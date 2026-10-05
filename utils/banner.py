from yuurisan import banner as yuri_banner, set_title as yuri_title


def show_banner(project_name):
    try:
        yuri_title(project_name)
    except Exception:
        pass
    yuri_banner(project_name)
