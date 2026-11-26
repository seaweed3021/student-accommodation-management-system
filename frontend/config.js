const COGNITO_CONFIG = {
  userPoolId: 'us-east-1_Kb4KJhT3X',
  clientId: '2fpqung9sp8v1n786fveo3g882'
};

const IS_LOCAL = ['localhost', '127.0.0.1'].includes(window.location.hostname);

const API_BASE_URL = IS_LOCAL
  ? 'http://localhost:8000'
  : 'https://https://d29rv8phlc.execute-api.us-east-1.amazonaws.com';