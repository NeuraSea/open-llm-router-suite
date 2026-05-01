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

import React, { useEffect } from 'react';
import { useTokenKeys } from '../../hooks/chat/useTokenKeys';
import { Spin } from '@douyinfe/semi-ui';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

const ChatPage = () => {
  const { t } = useTranslation();
  const { id } = useParams();
  const { keys, serverAddress, isLoading } = useTokenKeys(id);

  const requiresKey = (link) =>
    link.includes('{key}') ||
    link.includes('{cherryConfig}') ||
    link.includes('{aionuiConfig}');

  const getChatLink = () => {
    if (!id) return '';
    let chats = localStorage.getItem('chats');
    if (!chats) return '';
    chats = JSON.parse(chats);
    if (!Array.isArray(chats) || chats.length === 0 || !chats[id]) return '';
    for (let k in chats[id]) {
      const link = chats[id][k];
      if (typeof link === 'string') return link;
    }
    return '';
  };

  const comLink = (link, key) => {
    // console.log('chatLink:', chatLink);
    if (!serverAddress || !link) return '';
    if (requiresKey(link) && !key) return '';
    link = link.replaceAll('{address}', encodeURIComponent(serverAddress));
    if (key) link = link.replaceAll('{key}', 'sk-' + key);
    return link;
  };

  const chatLink = getChatLink();
  const redirectUrl =
    chatLink && (!requiresKey(chatLink) || keys.length > 0)
      ? comLink(chatLink, keys[0])
      : '';

  useEffect(() => {
    if (!isLoading && redirectUrl) {
      window.location.replace(redirectUrl);
    }
  }, [isLoading, redirectUrl]);

  return (
    <div className='fixed inset-0 w-screen h-screen flex items-center justify-center bg-white/80 z-[1000] mt-[60px]'>
      <div className='flex flex-col items-center'>
        <Spin size='large' spinning={true} tip={null} />
        <span
          className='whitespace-nowrap mt-2 text-center'
          style={{ color: 'var(--semi-color-primary)' }}
        >
          {t('正在跳转...')}
        </span>
      </div>
    </div>
  );
};

export default ChatPage;
