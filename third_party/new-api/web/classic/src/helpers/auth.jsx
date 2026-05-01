/*
Copyright (C) 2025 QuantumNous

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

For commercial licensing, please contact support@quantumnous.com
*/

import React, { useContext, useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { UserContext } from '../context/User';
import { API, updateAPI } from './api';
import { history } from './history';

export function authHeader() {
  // return authorization header with jwt token
  let user = JSON.parse(localStorage.getItem('user'));

  if (user && user.token) {
    return { Authorization: 'Bearer ' + user.token };
  } else {
    return {};
  }
}

function readStoredUser() {
  const raw = localStorage.getItem('user');
  if (!raw) return undefined;
  try {
    return JSON.parse(raw);
  } catch (e) {
    localStorage.removeItem('user');
    return undefined;
  }
}

export function storeSessionUser(user, userDispatch) {
  if (!user?.id) return;
  localStorage.setItem('user', JSON.stringify(user));
  localStorage.setItem('uid', String(user.id));
  updateAPI();
  if (userDispatch) {
    userDispatch({ type: 'login', payload: user });
  }
}

export async function syncSessionUser(userDispatch) {
  const storedUser = readStoredUser();
  if (storedUser) {
    if (userDispatch) {
      userDispatch({ type: 'login', payload: storedUser });
    }
    return storedUser;
  }

  const response = await API.get('/api/user/self', {
    skipErrorHandler: true,
  });
  const { success, data } = response.data || {};
  if (success && data?.id) {
    storeSessionUser(data, userDispatch);
    return data;
  }
  return undefined;
}

function useSessionUser() {
  const [, userDispatch] = useContext(UserContext);
  const [state, setState] = useState(() => ({
    checked: Boolean(readStoredUser()),
    user: readStoredUser(),
  }));

  useEffect(() => {
    if (state.user) {
      userDispatch({ type: 'login', payload: state.user });
      return;
    }

    let cancelled = false;
    syncSessionUser(userDispatch)
      .then((user) => {
        if (!cancelled) {
          setState({ checked: true, user });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ checked: true, user: undefined });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [state.user, userDispatch]);

  return state;
}

export const AuthRedirect = ({ children }) => {
  const { checked, user } = useSessionUser();

  if (user) {
    return <Navigate to='/console' replace />;
  }
  if (!checked) {
    return null;
  }

  return children;
};

function PrivateRoute({ children }) {
  const { checked, user } = useSessionUser();

  if (!checked) {
    return null;
  }
  if (!user) {
    return <Navigate to='/login' state={{ from: history.location }} />;
  }
  return children;
}

export function AdminRoute({ children }) {
  const { checked, user } = useSessionUser();

  if (!checked) {
    return null;
  }
  if (!user) {
    return <Navigate to='/login' state={{ from: history.location }} />;
  }
  if (typeof user.role === 'number' && user.role >= 10) {
    return children;
  }
  return <Navigate to='/forbidden' replace />;
}

export { PrivateRoute };
