from paneterm.file_tree_model import Entry, TreeModel


class Quiet:
    def rows_changed(self, *a): ...
    def node_changed(self, node): ...
    def request_listing(self, node, token):
        self.last = (node, token)

    def watch_changed(self, node, watched): ...
    def scroll_to(self, node): ...


def names(model):
    return [n.name for n in model.visible]


def build(always: frozenset[str]):
    listener = Quiet()
    model = TreeModel(listener, show_hidden=False)
    model.always_shown = always
    model.set_root("/r")
    entries = [
        Entry("src", "/r/src", True),
        Entry(".git", "/r/.git", True),
        Entry(".gitignore", "/r/.gitignore", False),
        Entry(".env", "/r/.env", False),
        Entry("a.txt", "/r/a.txt", False),
    ]
    model.apply_listing(*listener.last[:1], entries, listener.last[1])
    return model


def test_named_dotfiles_stay_visible_while_hidden_files_are_hidden():
    model = build(frozenset({".gitignore"}))
    assert names(model) == ["src", "a.txt", ".gitignore"] or set(names(model)) == {
        "src",
        "a.txt",
        ".gitignore",
    }


def test_without_the_option_all_dotfiles_hide():
    assert set(names(build(frozenset()))) == {"src", "a.txt"}


def test_show_hidden_still_shows_everything():
    model = build(frozenset({".gitignore"}))
    model.set_show_hidden(True)
    assert {".git", ".env", ".gitignore"} <= set(names(model))
