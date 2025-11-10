#%%

print("hello world")
# %%


class Foo:
    DOCENT_ENABLED: bool = True

    @classmethod
    def set_docent_enabled(cls, enabled: bool) -> None:
        cls.DOCENT_ENABLED = enabled


    def get_docent_enabled(self) -> bool:
        return self.DOCENT_ENABLED


# %%

Foo().get_docent_enabled()
# %%


Foo.set_docent_enabled(False)
# %%

Foo().get_docent_enabled()
# %%