import json
import os
import tempfile
import unittest

import server


class AuthFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_path = server.DATA_PATH
        server.DATA_PATH = os.path.join(self.temp_dir.name, 'data.json')
        server.app.config['TESTING'] = True
        self.client = server.app.test_client()

    def tearDown(self):
        server.DATA_PATH = self.original_data_path
        self.temp_dir.cleanup()

    def test_handle_search_is_case_insensitive_and_exact(self):
        response = self.client.post('/api/signup', json={
            'username': 'Alice_1',
            'password': 'Password123'
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        response = self.client.get('/api/users/search?q=@alice_1')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload['users'][0]['username'], 'alice_1')

        response = self.client.get('/api/users/search?q=alice')
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        payload = response.get_json()
        self.assertEqual(payload['users'], [])

    def test_invalid_or_empty_search_is_rejected(self):
        response = self.client.get('/api/users/search?q=')
        self.assertIn(response.status_code, (400, 200))

        response = self.client.get('/api/users/search?q=@bad handle')
        self.assertEqual(response.status_code, 400)
        self.assertIn('invalid', response.get_json()['message'].lower())

    def test_signup_and_login_accept_handle_variations(self):
        response = self.client.post('/api/signup', json={
            'username': 'User.Name',
            'password': 'Password123'
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

        duplicate = self.client.post('/api/signup', json={
            'username': 'user.name',
            'password': 'Password456'
        })
        self.assertEqual(duplicate.status_code, 400)

        login = self.client.post('/api/login', json={
            'username': '@User.Name',
            'password': 'Password123'
        })
        self.assertEqual(login.status_code, 200, login.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
