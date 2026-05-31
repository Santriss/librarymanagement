from locust import HttpUser, task, between

class LibraryUser(HttpUser):
    wait_time = between(1, 3)
    host = "https://librarymanagement-production-839c.up.railway.app"

    @task(3)
    def home(self):
        self.client.get("/")

    @task(2)
    def about(self):
        self.client.get("/aboutus")

    @task(1)
    def contact(self):
        self.client.get("/contactus")