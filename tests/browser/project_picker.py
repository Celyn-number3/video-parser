"""Exercise the actual grouped picker, not a hidden native-select test hook."""
def select_project(picker, identifier):
    picker.click()
    picker.page.locator('.project-picker-popup [role=option][data-project-id="'+identifier+'"]' ).click()
