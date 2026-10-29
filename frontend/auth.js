const userPool = new AmazonCognitoIdentity.CognitoUserPool({
  UserPoolId: COGNITO_CONFIG.userPoolId,
  ClientId: COGNITO_CONFIG.clientId
});

function signUp(email, password, onOk, onErr) {
  const attrs = [new AmazonCognitoIdentity.CognitoUserAttribute({ Name: 'email', Value: email })];
  userPool.signUp(email, password, attrs, null, (err, result) => err ? onErr(err) : onOk(result));
}

function confirmSignUp(email, code, onOk, onErr) {
  const user = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool });
  user.confirmRegistration(code, true, (err, res) => err ? onErr(err) : onOk(res));
}

function resendCode(email, onOk, onErr) {
  const user = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool });
  user.resendConfirmationCode((err, res) => err ? onErr(err) : onOk(res));
}

function signIn(email, password, onOk, onErr) {
  const user = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool });
  const details = new AmazonCognitoIdentity.AuthenticationDetails({ Username: email, Password: password });
  user.authenticateUser(details, {
    onSuccess: (session) => {
      const groups = session.getIdToken().decodePayload()['cognito:groups'] || [];
      onOk(groups);
    },
    onFailure: onErr
  });
}

function signOut() {
  const user = userPool.getCurrentUser();
  if (user) user.signOut();
}

function requireLogin(onReady) {
  const user = userPool.getCurrentUser();
  if (!user) { window.location.href = 'login.html'; return; }
  user.getSession((err, session) => {
    if (err || !session.isValid()) { window.location.href = 'login.html'; return; }
    const groups = session.getIdToken().decodePayload()['cognito:groups'] || [];
    onReady(groups);
  });
}