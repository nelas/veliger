#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# VÉLIGER
# Copyleft 2010-2013 - Bruno C. Vellutini | organelas.com
#
#

'''Editor de metadados do banco de imagens do CEBIMar-USP.

Este programa abre imagens, lê seus metadados (IPTC e EXIF) e fornece uma
interface para editar estas informações. Os campos foram adaptados para o
propósito do banco, que é divulgar imagens com conteúdo biológico.

Campos editáveis: título, legenda, marcadores, táxon, espécie, especialista,
autor, direitos, tamanho, local, cidade, estado e país.

Centro de Biologia Marinha da Universidade de São Paulo.
'''

import logging
import operator
import os
import pickle
import pyexiv2  # Versão 0.3.0
import re
import sys
import subprocess
import time
from datetime import datetime
from PIL import Image
from shutil import copy
from urllib import urlretrieve

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.QtWebKit import *

from mendeley import Mendeley  # Referências
from iptcinfo import IPTCInfo  # iptcinfo.py

# Gerado com: pyrcc4 -o recursos.py recursos.qrc
import recursos

__author__ = 'Bruno Vellutini'
__copyright__ = 'Copyright 2010-2013, CEBIMar/USP'
__credits__ = 'Bruno C. Vellutini'
__license__ = 'DEFINIR'
__version__ = '0.9.6'
__maintainer__ = 'Bruno Vellutini'
__email__ = 'organelas@gmail.com'
__status__ = 'Development'


class MainWindow(QMainWindow):
    '''Janela principal do programa.

    Inicia as instâncias dos outros componentes e aguarda interação do usuário.
    '''
    def __init__(self):
        QMainWindow.__init__(self)
        # Truque para evitar segfault ao fechar o programa.
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        # Definições
        #XXX Global pela facilidade de acesso. Melhorar eventualmente.
        global mainWidget
        global options
        mainWidget = MainTable(self, datalist, header)
        self.model = mainWidget.model
        self.automodels = AutoModels(autolists)
        options = PrefsDialog(self)
        self.help = ManualDialog(self)
        self.about = AboutDialog(self)

        # Objeto que guarda valores copiados.
        self.copied = []

        # Right click menu
        self.rightmenu = RightClickMenu(self)

        # Dock com thumbnail
        self.dockThumb = DockThumb(self)
        self.thumbDockWidget = QDockWidget(u'Thumbnail', self)
        self.thumbDockWidget.setWidget(self.dockThumb)
        # Dock com lista de updates
        self.dockUnsaved = DockUnsaved(self)
        self.unsavedDockWidget = QDockWidget(u'Modificadas', self)
        self.unsavedDockWidget.setWidget(self.dockUnsaved)
        # Dock com geolocalização
        self.dockGeo = DockGeo(self)
        self.geoDockWidget = QDockWidget(u'Geolocalização', self)
        self.geoDockWidget.setWidget(self.dockGeo)
        # Dock com editor de metadados
        self.dockEditor = DockEditor(self)
        self.editorDockWidget = QDockWidget(u'Editor', self)
        self.editorDockWidget.setAllowedAreas(
                Qt.TopDockWidgetArea |
                Qt.BottomDockWidgetArea)
        self.editorDockWidget.setWidget(self.dockEditor)
        # Dock com lista de referências
        self.dockRefs = DockRefs(self)
        self.refsDockWidget = QDockWidget(u'Referências', self)
        self.refsDockWidget.setWidget(self.dockRefs)

        # Timer
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)

        # Live editing
        self.live_edit = None

        # Atribuições da MainWindow
        self.setCentralWidget(mainWidget)
        self.setWindowTitle(u'Véliger - Editor de Metadados')
        self.setWindowIcon(QIcon(u':/appicon.svg'))
        self.statusBar().showMessage(u'Pronto para editar!', 2000)
        self.menubar = self.menuBar()

        ## Ações do menu
        # Sair
        self.exit = QAction(QIcon(u':/desligar.png'), u'Sair', self)
        self.exit.setShortcut('Ctrl+Q')
        self.exit.setStatusTip(u'Fechar o programa')
        self.connect(self.exit, SIGNAL('triggered()'), SLOT('close()'))

        # Abrir arquivo(s)
        self.openFile = QAction(QIcon(u':/arquivo.png'),
                u'Abrir arquivo(s)', self)
        self.openFile.setShortcut('Ctrl+O')
        self.openFile.setStatusTip(u'Abrir imagens')
        self.connect(self.openFile, SIGNAL('triggered()'),
                self.openfile_dialog)

        # Abrir pasta
        self.openDir = QAction(QIcon(u':/pasta.png'),
                u'Abrir pasta(s)', self)
        self.openDir.setShortcut('Ctrl+D')
        self.openDir.setStatusTip(u'Abrir pasta')
        self.connect(self.openDir, SIGNAL('triggered()'),
                self.opendir_dialog)

        # Copiar metadados
        self.copyMeta = QAction(QIcon(u':/copiar.png'),
                u'Copiar metadados', self)
        self.copyMeta.setShortcut('Ctrl+C')
        self.copyMeta.setStatusTip(u'Copiar metadados da entrada selecionada')
        self.connect(self.copyMeta, SIGNAL('triggered()'), self.copydata)

        # Colar metadados
        self.pasteMeta = QAction(QIcon(u':/colar.png'),
                u'Colar metadados', self)
        self.pasteMeta.setShortcut('Ctrl+V')
        self.pasteMeta.setStatusTip(
                u'Colar metadados na(s) entrada(s) selecionada(s)')
        self.connect(self.pasteMeta, SIGNAL('triggered()'), self.pastedata)

        # Deletar entrada(s)
        self.delRow = QAction(QIcon(u':/deletar.png'),
                u'Deletar entrada(s)', self)
        self.delRow.setShortcut('Ctrl+W')
        self.delRow.setStatusTip(u'Deletar entrada')
        self.connect(self.delRow, SIGNAL('triggered()'), self.delcurrent)

        # Gravar metadados nas imagens
        self.writeMeta = QAction(QIcon(u':/salvar.png'),
                u'Gravar metadados', self)
        self.writeMeta.setShortcut('Ctrl+S')
        self.writeMeta.setStatusTip(u'Gravar metadados na imagem')
        self.connect(self.writeMeta, SIGNAL('triggered()'),
                self.commitmeta)
        salvo = lambda: self.changeStatus(
                u'Metadados gravados na(s) imagem(ns)')
        self.writeMeta.triggered.connect(salvo)

        # Limpar tabela
        self.delAll = QAction(QIcon(u':/deletar.png'),
                u'Limpar tabela', self)
        self.delAll.setStatusTip(u'Deletar todas as entradas')
        self.connect(self.delAll, SIGNAL('triggered()'), self.cleartable)

        # Conversor para UTF-8
        self.convertChar = QAction(QIcon(u':/conversor.png'),
                u'Converter codificação (Latin-1 -> UTF-8)', self)
        self.convertChar.setStatusTip(
                u'Converter metadados das imagens selecionadas de Latin-1' +
                ' para UTF-8, use com cautela')
        self.connect(self.convertChar, SIGNAL('triggered()'),
                self.charconverter)

        # Opções
        self.openPref = QAction(QIcon(u':/options.png'),
                u'Opções', self)
        self.openPref.setStatusTip(u'Abrir opções do programa')
        self.connect(self.openPref, SIGNAL('triggered()'),
                self.openpref_dialog)

        self.openManual = QAction(QIcon(u':/manual.png'),
                u'Manual', self)
        self.openManual.setStatusTip(u'Abrir manual de instruções do programa')
        self.connect(self.openManual, SIGNAL('triggered()'),
                self.openmanual_dialog)

        # Sobre o programa
        self.openAbout = QAction(QIcon(u':/sobre.png'),
                u'Sobre', self)
        self.openAbout.setStatusTip(u'Sobre o programa')
        self.connect(self.openAbout, SIGNAL('triggered()'),
                self.openabout_dialog)

        # Toggle dock widgets
        self.toggleThumb = self.thumbDockWidget.toggleViewAction()
        self.toggleThumb.setShortcut('Shift+T')
        self.toggleThumb.setStatusTip(u'Esconde ou mostra o dock com thumbnails')
        self.toggleGeo = self.geoDockWidget.toggleViewAction()
        self.toggleGeo.setShortcut('Shift+G')
        self.toggleGeo.setStatusTip(u'Esconde ou mostra o dock com geolocalização')
        self.toggleEditor = self.editorDockWidget.toggleViewAction()
        self.toggleEditor.setShortcut('Shift+E')
        self.toggleEditor.setStatusTip(u'Esconde ou mostra o dock com o editor')
        self.toggleUnsaved = self.unsavedDockWidget.toggleViewAction()
        self.toggleUnsaved.setShortcut('Shift+U')
        self.toggleUnsaved.setStatusTip(u'Esconde ou mostra o dock com modificadas')
        self.toggleRefs = self.refsDockWidget.toggleViewAction()
        self.toggleRefs.setShortcut('Shift+R')
        self.toggleRefs.setStatusTip(u'Esconde ou mostra o dock com referências')

        # Tabela
        self.clearselection = QAction(u'Limpar seleção', self)
        self.clearselection.setShortcut('Esc')
        self.clearselection.triggered.connect(self.clear)
        self.addAction(self.clearselection)

        ## Menu
        # Arquivo
        self.arquivo = self.menubar.addMenu(u'&Arquivo')
        self.arquivo.addAction(self.openFile)
        self.arquivo.addAction(self.openDir)
        self.arquivo.addSeparator()
        self.arquivo.addAction(self.writeMeta)
        self.arquivo.addSeparator()
        self.arquivo.addAction(self.exit)

        # Editar
        self.editar = self.menubar.addMenu(u'&Editar')
        self.editar.addAction(self.delAll)
        self.editar.addSeparator()
        self.editar.addAction(self.copyMeta)
        self.editar.addAction(self.pasteMeta)
        self.editar.addAction(self.delRow)
        self.editar.addSeparator()
        self.editar.addAction(self.convertChar)
        self.editar.addSeparator()
        self.editar.addAction(self.openPref)

        # Janela
        self.janela = self.menubar.addMenu(u'&Janela')
        self.janela.addAction(self.toggleEditor)
        self.janela.addAction(self.toggleThumb)
        self.janela.addAction(self.toggleGeo)
        self.janela.addAction(self.toggleUnsaved)
        self.janela.addAction(self.toggleRefs)

        # Ajuda
        self.ajuda = self.menubar.addMenu(u'&Ajuda')
        self.ajuda.addAction(self.openManual)
        self.ajuda.addSeparator()
        self.ajuda.addAction(self.openAbout)

        # Toolbar
        self.toolbar = self.addToolBar(u'Ações')
        self.toolbar.addAction(self.openFile)
        self.toolbar.addAction(self.openDir)
        self.toolbar.addAction(self.copyMeta)
        self.toolbar.addAction(self.pasteMeta)
        self.toolbar.addAction(self.delRow)
        self.toolbar = self.addToolBar(u'Sair')
        self.toolbar.addAction(self.writeMeta)
        self.toolbar.addAction(self.exit)

        # Docks
        self.addDockWidget(Qt.RightDockWidgetArea, self.thumbDockWidget)
        self.addDockWidget(Qt.RightDockWidgetArea, self.unsavedDockWidget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.refsDockWidget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.geoDockWidget)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.editorDockWidget)
        self.tabifyDockWidget(self.unsavedDockWidget, self.thumbDockWidget)
        self.tabifyDockWidget(self.refsDockWidget, self.geoDockWidget)
        self.tabifyDockWidget(self.refsDockWidget, self.editorDockWidget)
        self.setTabPosition(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea,
                QTabWidget.North)
        #self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        # Lê opções do programa
        self.readsettings()

        # Conexões
        self.connect(self.geoDockWidget,
                SIGNAL('visibilityChanged(bool)'),
                self.istab_selected)

        self.connect(self.dockUnsaved,
                SIGNAL('syncSelection(PyQt_PyObject)'),
                self.setselection)

        self.connect(self.dockRefs,
                SIGNAL('refSync(PyQt_PyObject)'),
                self.sync_refs)

        # Live update
        self.connect(self.timer,
                SIGNAL('timeout()'),
                self.finish)

        # Context menu
        self.connect(mainWidget,
                SIGNAL('customContextMenuRequested(QPoint)'),
                self.rightclick)

    def rightclick(self, position):
        '''Identifica quem está sendo editado.'''
        self.rightmenu.popup(mainWidget.mapToGlobal(position))

    def whoislive(self, sender):
        '''Identifica quem está sendo editado.'''
        self.live_edit = sender

    def has_changed(self, sender):
        '''Verifica se o conteúdo do campo mudou.

        Chamado antes de iniciar o timer.
        '''
        if sender.objectName() == u'Tamanho' or sender.objectName() == u'Data':
            return True
        elif self.sender().inherits('QCompleter'):
            # Se o objeto for autocomplete, declarar modificado.
            return True
        else:
            return sender.isModified()

    def runtimer(self):
        '''Inicia o timer caso o objeto esteja modificado.'''
        # Verifica se foi modificado.
        modified = self.has_changed(self.sender())
        # Identifica objeto que está sendo editado.
        self.whoislive(self.sender())
        # Inicia o timer se o objeto estiver modificado.
        if modified:
            self.timer.start(100)

    def finish(self, autocomplete=''):
        '''Desencadeia o processo de salvar.

        Pode ser chamada diretamente, sem o timer. Usado mais pelo auto
        complete.
        '''
        # Parar o timer evita q o cursor volte para o campo.
        if self.timer.isActive():
            self.timer.stop()
        # Caso precise identificar o sender algum dia:
        # self.sender().inherits('QTimer')
        self.savedata(self.live_edit, autocomplete)
        logger.debug('Salvou...')

    def clear(self):
        '''Limpa seleção das tabelas.'''
        self.dockUnsaved.view.selectionModel.clearSelection()
        mainWidget.selectionModel.clearSelection()

    def istab_selected(self, visible):
        self.emit(SIGNAL('mapVisibility(PyQt_PyObject)'), visible)

    def copydata(self):
        '''Copia metadados da entrada selecionada.

        Metadados são salvos no objeto self.copied, como lista.
        '''
        if self.dockEditor.values:
            values = self.dockEditor.values
            self.copied = [value[1] for value in values]
            self.changeStatus(u'Metadados copiados de %s' % values[0][1], 5000)
            logger.debug('Metadados copiados de %s', values[0][1])

    def choose_one(self, first, second):
        '''Escolhe um entre dois objetos.

        O primeiro tem prioridade sobre o segundo. Se ele existir, já será
        escolhido.

        Utilizado para decidir qual valor salvar, o emitido pelo autocomplete
        ou o valor que está no campo. Note que o campo não reconhece quando o
        valor do autocomplete é completado, por isso essa função existe; talvez
        seja um bug.
        '''
        if first:
            return first
        else:
            return second

    def put_dot(self, caption):
        '''Coloca ponto final em legendas, se precisar.'''
        if caption:
            # Necessário para lidar com str e QString.
            try:
                if not caption.endswith('.'):
                    caption = caption + '.'
            except:
                if not caption.endsWith('.'):
                    caption = caption + '.'
        return caption

    def savedata(self, field, autocomplete):
        '''Salva valor do campo que está sendo editado para a tabela.

        Usa o nome do objeto (designado na criação) para identificar o campo
        que está sendo editado. Apenas um campo será salvo (mas pode ser salvo
        em múltiplas entradas).
        '''
        # Guarda entradas selecionadas para edição múltipla.
        indexes = mainWidget.selectedIndexes()
        rows = [index.row() for index in indexes]
        rows = list(set(rows))
        nrows = len(rows)

        # Salva posição do cursor.
        if not field.objectName() == u'Data':
            try:
                cursor = field.cursorPosition()
            except:
                logger.debug('Não capturou cursor...')

        # Inicia live update da tabela.
        if field.objectName() == u'Título':
            for row in rows:
                index = mainWidget.model.index(row, 1, QModelIndex())
                mainWidget.model.setData(index,
                    QVariant(self.dockEditor.titleEdit.text()), Qt.EditRole)
        elif field.objectName() == u'Legenda':
            for row in rows:
                index = mainWidget.model.index(row, 2, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.put_dot(self.dockEditor.captionEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'Marcadores':
            for row in rows:
                index = mainWidget.model.index(row, 3, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(unicode(self.choose_one(autocomplete,
                            self.dockEditor.tagsEdit.text())).lower()),
                        Qt.EditRole)
        elif field.objectName() == u'Táxon':
            for row in rows:
                index = mainWidget.model.index(row, 4, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.taxonEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'Especialista':
            for row in rows:
                index = mainWidget.model.index(row, 5, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.sourceEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'Autor':
            for row in rows:
                index = mainWidget.model.index(row, 6, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.authorEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'Direitos':
            for row in rows:
                index = mainWidget.model.index(row, 7, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.rightsEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'Tamanho':
            for row in rows:
                index = mainWidget.model.index(row, 8, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.dockEditor.sizeEdit.currentText()), Qt.EditRole)
        elif field.objectName() == u'Local':
            for row in rows:
                index = mainWidget.model.index(row, 9, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.locationEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'Cidade':
            for row in rows:
                index = mainWidget.model.index(row, 10, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.cityEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'Estado':
            for row in rows:
                index = mainWidget.model.index(row, 11, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.stateEdit.text())),
                        Qt.EditRole)
        elif field.objectName() == u'País':
            for row in rows:
                index = mainWidget.model.index(row, 12, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.choose_one(autocomplete,
                            self.dockEditor.countryEdit.text())),
                            Qt.EditRole)
        elif field.objectName() == u'Latitude':
            for row in rows:
                index = mainWidget.model.index(row, 13, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.dockGeo.lat.text()), Qt.EditRole)
        elif field.objectName() == u'Longitude':
            for row in rows:
                index = mainWidget.model.index(row, 14, QModelIndex())
                mainWidget.model.setData(index,
                        QVariant(self.dockGeo.long.text()), Qt.EditRole)
        elif field.objectName() == u'Data':
            current_date = self.dockThumb.dateedit.dateTime()
            for row in rows:
                index = mainWidget.model.index(row, 15, QModelIndex())
                mainWidget.model.setData(index,
                    QVariant(self.dockThumb.iodate(current_date)), Qt.EditRole)
            self.dockThumb.edited = False

        # Salva o current para evitar que volte para 0 após reset()
        oldindex = mainWidget.selectionModel.currentIndex()
        # Gambiarra para atualizar os valores da tabela
        mainWidget.selectionModel.reset()
        # Aplica o current para evitar que volte para 0 após reset()
        mainWidget.selectionModel.setCurrentIndex(oldindex, QItemSelectionModel.Select)
        # Mantém selecionado o que estava selecionado
        for index in indexes:
            mainWidget.selectionModel.select(index,
                    QItemSelectionModel.Select)
        # Volta cursor para posição
        if not field.objectName() == u'Data':
            try:
                field.setCursorPosition(cursor)
            except:
                logger.debug('Não deu certo reposicionar o cursor.')

        self.changeStatus(u'%d entrada(s) alterada(s)!' % nrows, 5000)
        logger.debug('%d entrada(s) alterada(s)!', nrows)

    def pastedata(self):
        '''Cola metadados na(s) entrada(s) selecionada(s).

        Usa valores guardados no objeto self.copied para colar nas entradas
        selecionadas.
        '''
        indexes = mainWidget.selectedIndexes()
        rows = [index.row() for index in indexes]
        rows = list(set(rows))
        nrows = len(rows)
        for index in indexes:
            # Título
            if index.column() == 1:
                mainWidget.model.setData(index,
                    QVariant(self.copied[1]), Qt.EditRole)
            # Legenda
            elif index.column() == 2:
                mainWidget.model.setData(index,
                    QVariant(self.copied[2]), Qt.EditRole)
            # Marcadores
            elif index.column() == 3:
                mainWidget.model.setData(index,
                    QVariant(unicode(self.copied[3]).lower()),
                    Qt.EditRole)
            # Táxon
            elif index.column() == 4:
                mainWidget.model.setData(index,
                        QVariant(self.copied[4]), Qt.EditRole)
            # Especialista
            elif index.column() == 5:
                mainWidget.model.setData(index,
                        QVariant(self.copied[5]), Qt.EditRole)
            # Autor
            elif index.column() == 6:
                mainWidget.model.setData(index,
                        QVariant(self.copied[6]), Qt.EditRole)
            # Direitos
            elif index.column() == 7:
                mainWidget.model.setData(index,
                        QVariant(self.copied[7]), Qt.EditRole)
            # Tamanho
            elif index.column() == 8:
                mainWidget.model.setData(index,
                    QVariant(self.copied[8]), Qt.EditRole)
            # Local
            elif index.column() == 9:
                mainWidget.model.setData(index,
                        QVariant(self.copied[9]), Qt.EditRole)
            # Cidade
            elif index.column() == 10:
                mainWidget.model.setData(index,
                        QVariant(self.copied[10]), Qt.EditRole)
            # Estado
            elif index.column() == 11:
                mainWidget.model.setData(index,
                        QVariant(self.copied[11]), Qt.EditRole)
            # País
            elif index.column() == 12:
                mainWidget.model.setData(index,
                        QVariant(self.copied[12]), Qt.EditRole)
            # Latitude
            elif index.column() == 13:
                mainWidget.model.setData(index,
                        QVariant(self.copied[13]), Qt.EditRole)
            # Longitude
            elif index.column() == 14:
                mainWidget.model.setData(index,
                        QVariant(self.copied[14]), Qt.EditRole)
            # Data
            elif index.column() == 15:
                mainWidget.model.setData(index,
                    QVariant(self.copied[15]), Qt.EditRole)

        # Gambiarra para atualizar os valores da tabela.
        mainWidget.setFocus(Qt.OtherFocusReason)
        self.changeStatus(u'%d entradas alteradas!' % nrows, 5000)
        logger.debug('%d entradas alteradas!', nrows)

    def openpref_dialog(self):
        '''Abre janela de opções.'''
        options.exec_()

    def openmanual_dialog(self):
        '''Abre janela do manual de instruções.'''
        self.help.exec_()

    def openabout_dialog(self):
        '''Abre janela sobre o programa.'''
        self.about.exec_()

    def charconverter(self):
        '''Converte codificação de Latin-1 para UTF-8.

        Pega a seleção da lista de imagens modificadas e procura a linha
        correspondente na tabela principal. Se o item não for encontrado o item
        na lista é apagado.

        Entrada convertida é adicionada no fim da tabela.
        '''

        critical = QMessageBox.critical(self,
                u'Cuidado!',
                u'As imagens selecionadas serão convertidas! ' \
                        u'Selecione apenas imagens que estejam com ' \
                        u'problemas na codificação de caracteres ' \
                        u'especiais (ç, à, ã, á)! Se nenhuma entrada ' \
                        u'estiver selecionada todas as imagens da ' \
                        u'tabela serão convertidas! Faça um backup das ' \
                        u'suas imagens antes de executar a conversão ' \
                        u'(é sério). Deseja prosseguir e converter os ' \
                        u'metadados da imagem de Latin-1 para UTF-8?',
                QMessageBox.Yes,
                QMessageBox.No)
        if critical == QMessageBox.Yes:
            entries = []
            n_all = 0
            indexes = mainWidget.selectionModel.selectedRows()
            if indexes:
                indexes = [index.row() for index in indexes]
                for row in indexes:
                    index = mainWidget.model.index(row, 0, QModelIndex())
                    filepath = mainWidget.model.data(index, Qt.DisplayRole)
                    entries.append(filepath.toString())
                self.delcurrent()
            else:
                for entry in self.model.mydata:
                    entries.append(entry[0])
                self.cleartable()
            for filepath in entries:
                entrymeta = self.createmeta(filepath, 'latin-1')
                self.model.insert_rows(0, 1, QModelIndex(), entrymeta)
                self.writemeta(entrymeta)
                n_all += 1
            self.changeStatus(
                    u'Metadados de %d figuras convertidos para UTF-8'
                    % n_all)
            logger.debug(u'Metadados de %d figuras convertidos para UTF-8',
                    n_all)
        else:
            self.changeStatus(u'Nenhuma imagem foi modificada')

    def sync_refs(self, references):
        '''Sincroniza referências da(s) entrada(s) selecionada(s).'''
        indexes = mainWidget.selectedIndexes()
        if indexes:
            for index in indexes:
                if index.column() == 17:
                    mainWidget.model.setData(
                            index,
                            QVariant(', '.join(references)),
                            Qt.EditRole)
            mainWidget.setFocus(Qt.OtherFocusReason)
        else:
            self.changeStatus(u'Nenhuma entrada selecionada.', 10000)

    def setselection(self, filename):
        '''Sincroniza seleção entre lista e tabela principal.

        Pega a seleção da lista de imagens modificadas e procura a linha
        correspondente na tabela principal. Se o item não for encontrado o item
        na lista é apagado.
        '''
        index = self.model.index(0, 0, QModelIndex())
        matches = self.model.match(index, 0, filename, -1,
                Qt.MatchContains)
        if len(matches) == 1:
            match = matches[0]
            mainWidget.selectRow(match.row())
        elif len(matches) == 0:
            mainWidget.selectionModel.clearSelection()
            mainWidget.emitlost(filename)
            self.changeStatus(u'%s não foi encontrada, importe-a novamente' % filename, 10000)
            logger.debug('%s não foi encontrada, importe-a novamente', filename)
        else:
            logger.debug('BAM! O que aconteceu aqui??? Descobrir.')
            #FIXME Não está funcionando..., mas para que serve isso?
            #for match in matches:
            #    mainWidget.selectionModel.select(match,
            #            QItemSelectionModel.Select)

    def commitmeta(self):
        '''Grava os metadados modificados na imagem.

        Pega lista de imagens modificadas, procura entrada na tabela principal
        e retorna os metadados. Chama função que gravará estes metadados na
        imagem. Chama função que emitirá o sinal avisando a gravação foi
        completada com sucesso.
        '''
        entries = self.dockUnsaved.mylist
        if entries:
            for entry in entries:
                index = self.model.index(0, 0, QModelIndex())
                matches = self.model.match(index, 0, entry, -1,
                        Qt.MatchContains)
                if len(matches) == 1:
                    values = []
                    match = matches[0]
                    for col in xrange(mainWidget.ncols):
                        index = self.model.index(match.row(), col, QModelIndex())
                        value = self.model.data(index, Qt.DisplayRole)
                        values.append(unicode(value.toString()))
                    filename = os.path.basename(values[0])
                    self.changeStatus(u'Gravando metadados em %s...' % filename)
                    write = self.writemeta(values)
                    if write == 0:
                        self.changeStatus(u'%s atualizado!' % filename)
                        logger.debug('Metadados gravados em %s!', filename)
                        continue
                    else:
                        break
            if write == 0:
                mainWidget.emitsaved()
            else:
                self.changeStatus(u'%s deu erro!' % filename, 5000)
                logger.warning('%s deu erro na hora da gravação!', filename)
                critical = QMessageBox()
                critical.setWindowTitle(u'Erro de gravação!')
                critical.setText(u'Metadados não foram gravados.')
                critical.setInformativeText(
                        u'%s pode ter mudado de local, nome ou ' % filename +
                        u'estar protegido contra gravação. Tente importá-lo ' +
                        u'novamente. O arquivo será retirado da lista de ' +
                        u'imagens modificadas. Deseja deletar a entrada da ' +
                        u'tabela principal também?')
                critical.setIcon(QMessageBox.Critical)
                critical.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                critical.exec_()
                self.setselection(filename)
                mainWidget.emitlost(filename)
                if critical == QMessageBox.Yes:
                    self.delcurrent()
        else:
            self.changeStatus(u'Lista de entradas modificadas está vazia')

    def writemeta(self, values):
        '''Grava os metadados no arquivo.

        Valores são salvos de acordo com os respectivos padrões, IPTC e EXIF.
        '''
        video_extensions = ('avi', 'AVI', 'mov', 'MOV', 'mp4', 'MP4', 'ogg',
                'OGG', 'ogv', 'OGV', 'dv', 'DV', 'mpg', 'MPG', 'mpeg', 'MPEG',
                'flv', 'FLV', 'm2ts', 'M2TS', 'wmv', 'WMV')
        if values[0].endswith(video_extensions):
            try:
                text_name = os.path.basename(values[0])
                new_name = text_name.split('.')[0] + '.txt'
                text_path = os.path.join(os.path.dirname(values[0]), new_name)
                meta_text = open(text_path, 'wb')
                logger.debug('Arquivo acessório criado para %s!', values[0])

                meta = {
                        'title': values[1],
                        'author': values[6],
                        'city': values[10],
                        'sublocation': values[9],
                        'state': values[11],
                        'country': values[12],
                        'taxon': values[4],
                        'rights': values[7],
                        'caption': self.put_dot(values[2]),
                        'size': values[8],
                        'source': values[5],
                        'date': values[15],
                        'latitude': values[13],
                        'longitude': values[14],
                        'references': values[17],
                        }

                # Lista com keywords
                if values[3] == '' or values[3] is None:
                    meta['tags'] = []
                else:
                    keywords = values[3].split(',')
                    keywords = [keyword.lower().strip() for keyword in keywords if keyword.strip() != '']
                    meta['tags'] = list(set(keywords))

                # Pickle meta
                if meta_text:
                    meta_dic = pickle.dump(meta, meta_text)
                    meta_text.close()
                    # Atualiza timestamp do arquivo, para cifonauta reconhecer.
                    os.utime(values[0], None)
            except:
                #FIXME Erro não está aparecendo...
                logger.warning('Erro na gravação do arquivo acessório.')
                self.changeStatus(u'ERRO!', 10000)
                critical = QMessageBox()
                critical.setWindowTitle(u'Erro!')
                critical.setText(u'Ocorreu algum erro na hora de gravar.')
                critical.setIcon(QMessageBox.Critical)
                critical.exec_()
            else:
                # Salva cache
                self.cachetable()
                return 0

        else:
            # Criar objeto com metadados
            info = IPTCInfo(values[0], force=True, inp_charset='utf-8')
            try:
                info.data['object name'] = values[1]                     # title
                info.data['caption/abstract'] = self.put_dot(values[2])  # caption
                info.data['headline'] = values[4]                        # taxon
                info.data['source'] = values[5]                          # source
                info.data['by-line'] = values[6]                         # author
                info.data['copyright notice'] = values[7]                # rights
                info.data['special instructions'] = values[8]            # size
                info.data['sub-location'] = values[9]                    # sublocation
                info.data['city'] = values[10]                           # city
                info.data['province/state'] = values[11]                 # state
                info.data['country/primary location name'] = values[12]  # country
                info.data['credit'] = values[17]                         # references

                # Lista com keywords
                if values[3] == '' or values[3] is None:
                    info.data['keywords'] = []                          # keywords
                else:
                    keywords = values[3].split(',')
                    keywords = [keyword.lower().strip() for keyword in keywords if
                            keyword.strip() != '']
                    info.data['keywords'] = list(set(keywords))         # keywords
                info.save()

                # Exif
                logger.info('Gravando EXIF de %s...', values[0])
                lat = values[13]
                long = values[14]
                image = self.dockGeo.get_exif(values[0])
                if lat and long:
                    newgps = self.dockGeo.geodict(lat, long)
                    self.changeStatus(u'Gravando novas coordenadas de %s...' %
                            values[0])
                    try:
                        image['Exif.GPSInfo.GPSLatitudeRef'] = str(newgps['latref'])
                        image['Exif.GPSInfo.GPSLatitude'] = (
                                newgps['latdeg'], newgps['latmin'], newgps['latsec'])
                        image['Exif.GPSInfo.GPSLongitudeRef'] = str(newgps['longref'])
                        image['Exif.GPSInfo.GPSLongitude'] = (
                                newgps['longdeg'], newgps['longmin'], newgps['longsec'])
                        image.write()
                        self.changeStatus(u'Gravando novas coordenadas de %s... pronto!' % values[0], 5000)
                        logger.debug('EXIF gravado em %s', values[0])
                    except:
                        self.changeStatus(u'Gravando novas coordenadas de %s... ERRO OCORREU!' % values[0], 5000)
                        logger.warning('Erro na gravação das coordenadas em %s...', values[0])
                else:
                    try:
                        self.changeStatus(u'Deletando o campo Exif.GPSInfo de %s...' % values[0])
                        image.__delitem__('Exif.GPSInfo.GPSLatitudeRef')
                        image.__delitem__('Exif.GPSInfo.GPSLatitude')
                        image.__delitem__('Exif.GPSInfo.GPSLongitudeRef')
                        image.__delitem__('Exif.GPSInfo.GPSLongitude')
                        image.write()
                        self.changeStatus(u'Deletando o campo Exif.GPSInfo de %s... pronto!' % values[0], 5000)
                        logger.debug('Campo Exif.GPSInfo de %s deletado!', values[0])
                    except:
                        self.changeStatus(u'Deletando o campo Exif.GPSInfo de %s... ERRO!' % values[0], 5000)
                        logger.debug('Erro para deletar Exif.GPSInfo de %s', values[0])

                # Data da criação da imagem
                if values[15]:
                    try:
                        newdate = datetime.strptime(values[15], '%Y-%m-%d %H:%M:%S')
                        image['Exif.Photo.DateTimeOriginal'] = newdate
                        image['Exif.Photo.DateTimeDigitized'] = newdate
                        image.write()
                    except:
                        logger.debug('Erro para gravar data de %s.', values[0])
                else:
                    try:
                        #TODO Decidir o que fazer aqui... deletar ou passar?
                        # Se nenhum valor estiver definido salvar padrão.
                        default_date = datetime(1900, 01, 01, 00, 00, 00)
                        image['Exif.Photo.DateTimeOriginal'] = default_date
                        image['Exif.Photo.DateTimeDigitized'] = default_date
                        #print 'Deletando datas de origem...'
                        #image.__delitem__('Exif.Photo.DateTimeOriginal')
                        #image.__delitem__('Exif.Photo.DateTimeDigitized')
                        #print image['Exif.Image.DateTime']
                        image.write()
                    except:
                        logger.debug('Erro para gravar data de %s.', values[0])

            except:
                logger.warning('Ocorreu algum erro.')
                self.changeStatus(u'ERRO!', 10000)
                critical = QMessageBox()
                critical.setWindowTitle(u'Erro!')
                critical.setText(u'Ocorreu algum erro na hora de gravar.')
                critical.setIcon(QMessageBox.Critical)
                critical.exec_()
            else:
                # Salva cache
                self.cachetable()
                return 0

    def changeStatus(self, status, duration=2000):
        '''Muda a mensagem de status da janela principal.'''
        self.statusBar().showMessage(status, duration)

    def openfile_dialog(self):
        '''Abre janela para escolher arquivos.

        Apenas arquivos terminados em jpg, jpeg, JPG e JPEG apareceram. Ele
        reconhece a posição do último arquivo aberto e checa a existência de
        possíveis duplicatas já presentes na tabela (baseado no nome do
        arquivo).
        '''
        self.openfile = QFileDialog()
        filepaths = self.openfile.getOpenFileNames(self,
                'Selecionar arquivo(s)',
                self.last_openfile, u'Imagens (*.jpg *.jpeg *.JPG *.JPEG);;Vídeos (*.avi *.AVI *.mov *.MOV *.mp4 *.MP4 *.ogg *.OGG *.ogv *.OGV *.dv *.DV *.mpg *.MPG *.mpeg *MPEG *.flv *.FLV *.wmv *.WMV *.m2ts *.M2TS')
        if filepaths:
            self.last_openfile = os.path.dirname(unicode(filepaths[0]))
            n_all = len(filepaths)
            n_new = 0
            n_dup = 0
            t0 = time.time()
            self.changeStatus(u'Importando %d imagens...' % n_all)
            for filepath in filepaths:
                filename = os.path.basename(unicode(filepath))
                matches = self.matchfinder(filename)
                if len(matches) == 0:
                    entrymeta = self.createmeta(filepath)
                    self.model.insert_rows(0, 1, QModelIndex(), entrymeta)
                    n_new += 1
                    logger.info('%s foi importada.', filepath)
                else:
                    n_dup += 1
                    logger.info('%s é duplicada.', filepath)
                    pass
            t1 = time.time()
            t = t1 - t0
            self.changeStatus(u'%d imagens analisadas em %.2f s,' % (n_all, t) +
                    u' %d novas e %d duplicadas' % (n_new, n_dup), 10000)
            logger.info('%d imagens analisadas em %.2f s', n_all, t)
            logger.info('%d novas e %d duplicadas', n_new, n_dup)
        # Salva cache
        self.cachetable()

    def opendir_dialog(self):
        '''Abre janela para selecionar uma pasta.

        Chama a função para varrer recursivamente a pasta selecionada. Lembra
        qual foi a última pasta escolhida.
        '''
        self.opendir = QFileDialog()
        folder = self.opendir.getExistingDirectory(
                self,
                'Selecione uma pasta',
                self.last_opendir,
                QFileDialog.ShowDirsOnly
                )
        if folder:
            self.last_opendir = unicode(folder)
            self.imgfinder(unicode(folder))

    def imgfinder(self, folder, apply_only=False):
        '''Busca recursivamente imagens na pasta selecionada.

        É possível definir as extensões a serem procuradas. Quando um arquivo é
        encontrado ele verifica se já está na tabela. Se não estiver, ele chama
        a função para extrair os metadados e insere uma nova entrada.
        '''
        n_all = 0
        n_new = 0
        n_dup = 0

        applylist = []

        # Tupla para o endswith()
        extensions = (
            'jpg', 'JPG', 'jpeg', 'JPEG', 'avi', 'AVI', 'mov',
            'MOV', 'mp4', 'MP4', 'ogg', 'OGG', 'ogv', 'OGV',
            'dv', 'DV', 'mpg', 'MPG', 'mpeg', 'MPEG', 'flv',
            'FLV', 'm2ts', 'M2TS', 'wmv', 'WMV'
            )

        t0 = time.time()

        logger.info('Buscando imagens em %s', folder)
        # Buscador de imagens em ação
        for root, dirs, files in os.walk(folder):
            for filename in files:
                if filename.endswith(extensions):
                    filepath = os.path.join(root, filename)
                    if not apply_only:
                        matches = self.matchfinder(filename)
                        if len(matches) == 0:
                            entrymeta = self.createmeta(filepath)
                            self.model.insert_rows(0, 1, QModelIndex(), entrymeta)
                            n_new += 1
                            logger.info('%s foi importada.', filepath)
                        else:
                            n_dup += 1
                            logger.info('%s é duplicada.', filepath)
                            pass
                        n_all += 1
                    else:
                        applylist.append(filepath)

        else:  # Se o número máximo de imagens for atingido, finalizar.
            if not apply_only:
                t1 = time.time()
                t = t1 - t0
                self.changeStatus(u'%d imagens analisadas em %.2f s,' % (n_all, t) +
                        u' %d novas e %d duplicadas' % (n_new, n_dup), 10000)
                logger.info('%d imagens analisadas em %.2f s', n_all, t)
                logger.info('%d novas e %d duplicadas', n_new, n_dup)
        if apply_only:
            return applylist
        # Salva cache
        self.cachetable()

    def createmeta(self, filepath, charset='utf-8'):
        '''Define as variáveis extraídas dos metadados (IPTC e EXIF) da imagem.

        Usa a biblioteca do arquivo iptcinfo.py e pyexiv. Retorna lista com
        valores.
        '''
        filepath = unicode(filepath)
        filename = os.path.basename(filepath)
        self.changeStatus(u'Lendo os metadados de %s e criando variáveis...' % filename)
        logger.info('Lendo metadados de %s...', filename)
        # Extensões
        photo_extensions = ('jpg', 'JPG', 'jpeg', 'JPEG')
        video_extensions = ('avi', 'AVI', 'mov', 'MOV', 'mp4', 'MP4', 'ogg', 'OGG', 'ogv', 'OGV', 'dv', 'DV', 'mpg', 'MPG', 'mpeg', 'MPEG', 'flv', 'FLV', 'm2ts', 'M2TS', 'wmv', 'WMV')

        meta = {}

        if filename.endswith(photo_extensions):
            type = 'photo'
            # Criar objeto com metadados
            # force=True permite editar imagem sem IPTC
            info = IPTCInfo(filepath, force=True, inp_charset=charset)
            # Checando se o arquivo tem dados IPTC
            if len(info.data) < 4:
                logger.debug('%s não tem dados IPTC!', filename)

            # Definindo as variáveis IPTC
            meta = {
                    'title': info.data['object name'],  # 5
                    'tags': info.data['keywords'],  # 25
                    'author': info.data['by-line'],  # 80
                    'city': info.data['city'],  # 90
                    'sublocation': info.data['sub-location'],  # 92
                    'state': info.data['province/state'],  # 95
                    'country': info.data['country/primary location name'],  # 101
                    'taxon': info.data['headline'],  # 105
                    'rights': info.data['copyright notice'],  # 116
                    'caption': info.data['caption/abstract'],  # 120
                    'genus_sp': info.data['original transmission reference'],  # 103
                    'size': info.data['special instructions'],  # 40
                    'source': info.data['source'],  # 115
                    'references': info.data['credit'],  # 110
                    }

            # Extraindo GPS
            exif = self.dockGeo.get_exif(filepath)
            gps = self.dockGeo.get_gps(exif)
            # Testa a integridade do GPS do EXIF olhando o latref.
            # Se estiver ok, continua. Talvez precise melhorar.
            if gps:
                if gps['latref']:
                    gps_str = self.dockGeo.gps_string(gps)
                    meta['latitude'] = gps_str['lat']
                    meta['longitude'] = gps_str['long']
                    logger.debug('GPS íntegro.')
                else:
                    meta['latitude'], meta['longitude'] = '', ''
            else:
                meta['latitude'], meta['longitude'] = '', ''

            # Extraindo data de criação da foto
            datedate = self.dockGeo.get_date(exif)
            # Caso o metadado esteja como string, tentar converter em datetime.
            if isinstance(datedate, str) or isinstance(datedate, bool):
                try:
                    logger.debug('Data como string, convertendo...')
                    meta['date'] = datetime.strptime(datedate, '%Y-%m-%d %H:%M:%S')
                except:
                    logger.debug('Algum erro ocorreu na conversão')
                    meta['date'] = ''
            else:
                meta['date'] = datedate.strftime('%Y-%m-%d %H:%M:%S')

        elif filename.endswith(video_extensions):
            type = 'video'
            meta = {
                    'title': u'',
                    'tags': u'',
                    'author': u'',
                    'city': u'',
                    'sublocation': u'',
                    'state': u'',
                    'country': u'',
                    'taxon': u'',
                    'rights': u'',
                    'caption': u'',
                    'size': u'',
                    'source': u'',
                    'date': '1900-01-01 01:01:01',
                    'latitude': u'',
                    'longitude': u'',
                    'references': u'',
                    }

            # Verifica se arquivo acessório com meta dos vídeos existe.
            try:
                text_path = filepath.split('.')[0] + '.txt'
                meta_text = open(text_path, 'rb')
                logger.debug('Arquivo de info já existe!')
            except:
                meta_text = ''

            if meta_text:
                try:
                    meta_dic = pickle.load(meta_text)
                    meta_text.close()
                    # Atualiza meta com valores do arquivo acessório.
                    meta.update(meta_dic)
                except:
                    logger.warning('Pickle is corrupted: %s', meta_text)

        # Criando timestamp
        meta['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S',
                time.localtime(os.path.getmtime(filepath)))

        # Cria a lista para tabela da interface
        entrymeta = [
                filepath,
                meta['title'],
                meta['caption'],
                ', '.join(meta['tags']),
                meta['taxon'],
                meta['source'],
                meta['author'],
                meta['rights'],
                meta['size'],
                meta['sublocation'],
                meta['city'],
                meta['state'],
                meta['country'],
                meta['latitude'],
                meta['longitude'],
                meta['date'],
                meta['timestamp'],
                meta['references'],
                ]
        if entrymeta[3] != '':
            entrymeta[3] = entrymeta[3] + ', '
        # Converte valores dos metadados vazios (None) para string em branco
        for index in [index for index, field in enumerate(entrymeta) if \
                field is None]:
            field = u''
            entrymeta[index] = field
        else:
            pass

        self.createthumbs(filepath, type)

        return entrymeta

    def createthumbs(self, filepath, type):
        '''Cria thumbnails para as fotos novas usando o PIL.'''
        hasdir(thumbdir)
        filename = os.path.basename(filepath)
        thumbs = os.listdir(thumbdir)
        thumbpath = os.path.join(thumbdir, filename)
        #TODO Ver um bom jeito para comparar arquivos.
        # try: hashlib, chunk and filecmp
        if type == 'photo':
            size = 400, 400
            copy(filepath, thumbdir)
            self.changeStatus(u'%s copiado para %s' % (filename, thumbdir))
            try:
                im = Image.open(thumbpath)
                im.thumbnail(size, Image.ANTIALIAS)
                im.save(thumbpath, 'JPEG')
                logger.debug('Thumb %s criado!', thumbpath)
            except:
                logger.warning('Thumb %s não foi criado!', thumbpath)

        elif type == 'video':
            #FIXME Tentar descobrir um jeito portável de fazer isso!
            # PythonMagick talvez?
            try:
                # Cria thumb grande a partir de 1 frame no segundo 5
                #FIXME Proporção dos vídeos HDs saem errada.
                subprocess.call(['ffmpeg', '-i', filepath, '-vframes', '1',
                    '-vf', 'scale=400:-1', '-ss', '1', '-f', 'image2', thumbpath])
                logger.debug('Thumb %s criado!', thumbpath)
            except:
                self.changeStatus(u'Não consegui criar o thumbnail...', 10000)
                logger.warning('Thumb %s não foi criado! FFMpeg está instalado?', thumbpath)

    def matchfinder(self, candidate):
        '''Verifica se entrada já está na tabela.

        O candidato pode ser o nome do arquivo (string) ou a entrada
        selecionada da tabela (lista). Retorna uma lista com duplicatas ou
        lista vazia caso nenhuma seja encontrada.
        '''
        index = self.model.index(0, 0, QModelIndex())
        if isinstance(candidate, list):
            value = os.path.basename(unicode(entry[0]))
            matches = self.model.match(index, 0, value, -1, Qt.MatchContains)
        else:
            matches = self.model.match(index, 0, candidate, -1, Qt.MatchContains)
        return matches

    def delcurrent(self):
        '''Deleta a(s) entrada(s) selecionada(s) da tabela.

        Verifica se a entrada a ser deletada está na lista de imagens
        modificadas. Se estiver, chama janela para o usuário decidir se quer
        apagar a entrada mesmo sem as modificações terem sido gravadas na
        imagem. Caso a resposta seja positiva a entrada será apagada e retirada
        da lista de imagens modificadas.
        '''
        indexes = mainWidget.selectionModel.selectedRows()
        if indexes:
            n_del = 0
            # Cria lista com linhas a serem deletadas
            indexes = [index.row() for index in indexes]
            unsaved = []
            for row in indexes:
                index = mainWidget.model.index(row, 0, QModelIndex())
                filepath = mainWidget.model.data(index, Qt.DisplayRole)
                filename = os.path.basename(unicode(filepath.toString()))
                if filename in self.dockUnsaved.mylist:
                    unsaved.append(filename)
                else:
                    continue
            #XXX Tem algum jeito de melhorar essa função? Repete sequência.
            if len(unsaved) > 0:
                warning = QMessageBox.warning(
                        self,
                        u'Atenção!',
                        u'As alterações não foram gravadas nas imagens.' \
                                u' Deseja apagá-las mesmo assim?',
                        QMessageBox.Yes,
                        QMessageBox.No)
                if warning == QMessageBox.Yes:
                    for filename in unsaved:
                        mainWidget.emitlost(filename)
                        logger.debug('%s modificado, mas será retirado da tabela', filename)
                    # Ordem decrescente previne contra o erro 'out of range'
                    # na hora de deletar diversas entradas
                    indexes.sort()
                    indexes.reverse()
                    for index in indexes:
                        self.model.remove_rows(index, 1, QModelIndex())
                        n_del += 1
                    self.changeStatus(u'%d entradas deletadas' % n_del)
                else:
                    self.changeStatus(
                            u'Nenhuma entrada apagada, grave as alterações', 10000)
            else:
                # Ordem decrescente previne contra o erro 'out of range'
                # na hora de deletar diversas entradas
                indexes.sort()
                indexes.reverse()
                for index in indexes:
                    self.model.remove_rows(index, 1, QModelIndex())
                    n_del += 1
                self.changeStatus(u'%d entradas deletadas' % n_del)
        else:
            self.changeStatus(u'Nenhuma entrada selecionada')
        # Salva cache
        self.cachetable()

    def cleartable(self):
        '''Remove todas as entradas da tabela.

        Antes de deletar checa se existem imagens não-salvas na lista.
        '''
        #XXX Ver se não dá pra melhorar... Repete sequência.
        if len(self.dockUnsaved.mylist) == 0:
            rows = self.model.rowCount(self.model)
            if rows > 0:
                self.model.remove_rows(0, rows, QModelIndex())
                self.changeStatus(u'%d entradas deletadas' % rows)
            else:
                self.changeStatus(u'Nenhuma entrada selecionada')
        else:
            warning = QMessageBox.warning(
                    self,
                    u'Atenção!',
                    u'As alterações não foram gravadas nas imagens.' \
                            u' Deseja apagá-las mesmo assim?',
                    QMessageBox.Yes,
                    QMessageBox.No)
            if warning == QMessageBox.Yes:
                rows = self.model.rowCount(self.model)
                if rows > 0:
                    self.model.remove_rows(0, rows, QModelIndex())
                    mainWidget.emitsaved()
                    self.changeStatus(u'%d entradas deletadas' % rows)
                else:
                    self.changeStatus(u'Nenhuma entrada selecionada')
        # Salva cache
        self.cachetable()

    def cachetable(self):
        '''Salva estado atual dos dados em arquivos externos.

        Cria backup dos conteúdos da tabela e da lista de imagens modificadas.
        '''
        #TODO Integrar com QSettings()? Tentei, mas o pickle não funcionou por
        # motivos de encoding e salvar a lista diretamente também não... :(
        self.changeStatus(u'Salvando backup...')
        # Tabela
        tablecache = open(tablepickle, 'wb')
        entries = mainWidget.model.mydata
        pickle.dump(entries, tablecache)
        tablecache.close()
        # Tabela referências
        refscache = open(refspickle, 'wb')
        entries = self.dockRefs.model.mydata
        pickle.dump(entries, refscache)
        refscache.close()
        # Lista
        listcache = open(listpickle, 'wb')
        entries = self.dockUnsaved.mylist
        pickle.dump(entries, listcache)
        listcache.close()
        # Completes
        autocache = open(autopickle, 'wb')
        for k, v in autolists.iteritems():
            comps = []
            ilist = eval('self.automodels.' + k + '.stringList()')
            for i in ilist:
                comps.append(i)
            autolists[k] = comps
        pickle.dump(autolists, autocache)
        autocache.close()
        logger.debug('Backup salvo nos arquivos: %s, %s, %s, %s', tablepickle,
                refspickle, listpickle, autopickle)

    def readsettings(self):
        '''Lê o estado anterior do aplicativo durante a inicialização.'''
        settings = QSettings()

        settings.beginGroup('main')
        self.resize(settings.value('size', QSize(1000, 740)).toSize())
        self.move(settings.value('position', QPoint(200, 0)).toPoint())
        self.last_openfile = settings.value('openfile').toString()
        self.last_opendir = settings.value('opendir').toString()
        settings.endGroup()

    def writesettings(self):
        '''Salva estado atual do aplicativo.'''
        settings = QSettings()

        settings.beginGroup('main')
        settings.setValue('size', self.size())
        settings.setValue('position', self.pos())
        settings.setValue('openfile', self.last_openfile)
        settings.setValue('opendir', self.last_opendir)
        settings.endGroup()

    def closeEvent(self, event):
        '''O que fazer quando o programa for fechado.'''
        self.cachetable()
        self.writesettings()
        event.accept()


class RightClickMenu(QMenu):
    '''Menu que aparece com o botão direito.'''
    def __init__(self, parent):
        QMenu.__init__(self, parent)

        self.parent = parent

        self.apply = QAction(u'Aplicar metadados em pasta', self)
        self.apply.triggered.connect(self.trial)
        self.addAction(self.apply)

    def trial(self):
        '''Verifica se apenas uma entrada está selecionada.'''
        selected = mainWidget.selectionModel.selectedRows()
        if not selected:
            warning = QMessageBox()
            warning.setWindowTitle(u'Nenhuma entrada selecionada')
            warning.setText(u'Selecione ao menos uma entrada!')
            warning.setInformativeText(
                    u'Para aplicar os metadados em uma pasta ao menos uma ' +
                    u'entrada da tabela principal deve estar selecionada.')
            warning.setIcon(QMessageBox.Warning)
            warning.setStandardButtons(QMessageBox.Ok)
            warning.exec_()
        elif len(selected) == 1:
            values = self.index_to_values(selected[0])
            self.open(values)
        else:
            warning = QMessageBox()
            warning.setWindowTitle(u'Mais de 1 entrada selecionada')
            warning.setText(u'Selecione apenas uma entrada!')
            warning.setInformativeText(
                    u'Para aplicar os metadados em uma pasta somente uma ' +
                    u'entrada da tabela principal deve estar selecionada.')
            warning.setIcon(QMessageBox.Warning)
            warning.setStandardButtons(QMessageBox.Ok)
            warning.exec_()

    def open(self, values):
        '''Abre janela para selecionar uma pasta.

        Chama a função para varrer recursivamente a pasta selecionada. Lembra
        qual foi a última pasta escolhida.
        '''
        opendir = QFileDialog()
        folder = opendir.getExistingDirectory(self,
                'Selecione uma pasta',
                self.parent.last_opendir,
                QFileDialog.ShowDirsOnly)
        if folder:
            self.parent.last_opendir = unicode(folder)
            filepaths = self.parent.imgfinder(unicode(folder), apply_only=True)
            self.write(values, folder, filepaths)

    def index_to_values(self, rowindex):
        '''Converte indexes em valores.'''
        values = []
        for col in xrange(mainWidget.ncols):
            index = mainWidget.model.index(rowindex.row(), col, QModelIndex())
            value = mainWidget.model.data(index, Qt.DisplayRole)
            values.append(unicode(value.toString()))
        return values

    def write(self, values, folder, filepaths):
        '''Executa o processo de gravação.'''
        janela = QMessageBox()
        janela.setWindowTitle(u'Confirme as informações abaixo')
        janela.setText(
                u'%d arquivos serão modificados na pasta %s' % (len(filepaths),
                    folder))
        janela.setInformativeText(u'Os metadados abaixo serão gravados nas ' +
                u'imagens selecionadas. Confira antes de continuar.\n' +
                u'\nTítulo:\t\t%s' % values[1] +
                u'\nLegenda:\t\t%s' % values[2] +
                u'\nMarcadores:\t%s' % values[3] +
                u'\nTamanho:\t\t%s' % values[9] +
                u'\nTáxon:\t\t%s' % values[4] +
                u'\nEspecialista:\t%s' % values[5] +
                u'\nAutor:\t\t%s' % values[6] +
                u'\nDireitos:\t\t%s' % values[7] +
                u'\nLocal:\t\t%s' % values[9] +
                u'\nCidade:\t\t%s' % values[10] +
                u'\nEstado:\t\t%s' % values[11] +
                u'\nPaís:\t\t%s' % values[12] +
                u'\nData:\t\t%s' % values[15] +
                u'\nLatitude:\t\t%s' % values[13] +
                u'\nLongitude:\t\t%s' % values[14] +
                u'\nReferências:\t%s' % values[17]
                )
        janela.setIcon(QMessageBox.Information)
        janela.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        result = janela.exec_()
        if result == QMessageBox.Ok:
            yes = 0
            no = 0
            for filepath in filepaths:
                values[0] = filepath
                wrote = self.parent.writemeta(values)
                if wrote == 0:
                    yes += 1
                    self.parent.changeStatus(u'%s atualizado!' % filepath)
                    logger.debug('%s atualizado!', filepath)
                else:
                    logger.debug('%s erro!', filepath)
                    no += 1
            self.parent.changeStatus(u'Sucesso! %d arquivos atualizados!' % yes)


class ManualDialog(QDialog):
    '''Janela do manual de instruções.'''
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        #TODO


class AboutDialog(QDialog):
    '''Janela com informações sobre o programa.'''
    def __init__(self, parent):
        QDialog.__init__(self, parent)
        #TODO


class PrefsDialog(QDialog):
    '''Janela de preferências.'''
    def __init__(self, parent):
        QDialog.__init__(self, parent)

        self.automodels = parent.automodels

        self.geral = PrefsGerais()
        self.autocomplete = EditCompletion(self)

        self.tabwidget = QTabWidget()
        self.tabwidget.addTab(self.geral, u'&Gerais')
        self.tabwidget.addTab(self.autocomplete, u'&Autocompletador')

        self.buttons = QDialogButtonBox(
                QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

        self.connect(self.buttons, SIGNAL('accepted()'), self,
                SLOT('accept()'))
        self.connect(self.buttons, SIGNAL('accepted()'), self.emitrebuild)
        self.connect(self.buttons, SIGNAL('rejected()'), self,
                SLOT('reject()'))

        self.layout = QVBoxLayout()
        self.layout.addWidget(self.tabwidget)
        self.layout.addWidget(self.buttons)
        self.setLayout(self.layout)

        self.setWindowTitle(u'Opções')

    def emitrebuild(self):
        '''Emite sinal com modelos atualizados e ordenados.'''
        models = dir(self.automodels)
        excludes = ['__doc__', '__init__', '__module__', 'autolists']
        for ex in excludes:
            models.remove(ex)
        for model in models:
            eval('self.automodels.' + model + '.sort(0)')
        self.emit(SIGNAL('rebuildcomplete(PyQt_PyObject)'), self.automodels)


class EditCompletion(QWidget):
    '''Editor dos valores para autocompletar campos de edição.'''
    def __init__(self, parent):
        QWidget.__init__(self, parent)

        self.lists = [
                u'Marcadores',
                u'Taxa',
                u'Especialistas',
                u'Autores',
                u'Direitos',
                u'Locais',
                u'Cidades',
                u'Estados',
                u'Países',
                ]
        self.automenu = QComboBox()
        self.automenu.addItems(self.lists)

        self.model = parent.automodels.tags
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setAlternatingRowColors(True)

        self.automodels = parent.automodels

        self.popmodels = QPushButton(
                u'&Extrair valores das imagens abertas', self)

        self.buttonbox = QWidget()
        self.insert = QPushButton(u'&Inserir', self)
        self.remove = QPushButton(u'&Remover', self)
        self.buttonhbox = QHBoxLayout()
        self.buttonhbox.addWidget(self.remove)
        self.buttonhbox.addWidget(self.insert)
        self.buttonbox.setLayout(self.buttonhbox)

        self.viewvbox = QVBoxLayout()
        self.viewvbox.addWidget(self.automenu)
        self.viewvbox.addWidget(self.buttonbox)
        self.viewvbox.addWidget(self.view)
        self.viewvbox.addWidget(self.popmodels)
        self.setLayout(self.viewvbox)

        self.connect(self.insert, SIGNAL('clicked()'),
                self.insertrow)
        self.connect(self.remove, SIGNAL('clicked()'),
                self.removerow)
        self.connect(self.popmodels, SIGNAL('clicked()'),
                self.populate)
        self.connect(self.automenu, SIGNAL('currentIndexChanged(QString)'),
                self.buildview)

    def buildview(self, modellist):
        '''Gera view do modelo escolhido.'''
        if modellist == u'Marcadores':
            self.model = self.automodels.tags
        elif modellist == u'Taxa':
            self.model = self.automodels.taxa
        elif modellist == u'Especialistas':
            self.model = self.automodels.sources
        elif modellist == u'Autores':
            self.model = self.automodels.authors
        elif modellist == u'Direitos':
            self.model = self.automodels.rights
        elif modellist == u'Locais':
            self.model = self.automodels.places
        elif modellist == u'Cidades':
            self.model = self.automodels.cities
        elif modellist == u'Estados':
            self.model = self.automodels.states
        elif modellist == u'Países':
            self.model = self.automodels.countries
        self.view.setModel(self.model)

    def insertrow(self):
        '''Insere linha no modelo.'''
        self.model.insertRows(0, 1, QModelIndex())

    def removerow(self):
        '''Remove linha do modelo.'''
        indexes = self.view.selectedIndexes()
        for index in indexes:
            self.model.removeRows(index.row(), 1, QModelIndex())

    def populate(self):
        '''Extrai valores das fotos e popula modelo.'''
        modellist = self.model.stringList()
        setlist = set(modellist)
        current = self.automenu.currentText()
        if current == u'Marcadores':
            col = 3
        elif current == u'Taxa':
            col = 4
        elif current == u'Especialistas':
            col = 5
        elif current == u'Autores':
            col = 6
        elif current == u'Direitos':
            col = 7
        elif current == u'Locais':
            col = 9
        elif current == u'Cidades':
            col = 10
        elif current == u'Estados':
            col = 11
        elif current == u'Países':
            col = 12

        rows = mainWidget.model.rowCount(mainWidget.model)

        if col == 3:
            all = []
            for row in xrange(rows):
                index = mainWidget.model.index(row, col, QModelIndex())
                value = mainWidget.model.data(index, Qt.DisplayRole)
                if unicode(value.toString()) != '':
                    taglist = value.toString().split(',')
                    for tag in taglist:
                        if tag.trimmed() != '':
                            all.append(tag.trimmed())
        else:
            all = []
            for row in xrange(rows):
                index = mainWidget.model.index(row, col, QModelIndex())
                value = mainWidget.model.data(index, Qt.DisplayRole)
                if unicode(value.toString()) != '':
                    all.append(value.toString())

        setall = set(all)
        finalset = setlist | setall
        self.model.setStringList(list(finalset))
        self.view.setModel(self.model)


class PrefsGerais(QWidget):
    '''Opções gerais do programa.'''
    def __init__(self):
        QWidget.__init__(self)
        #TODO


class MainTable(QTableView):
    '''Tabela principal com entradas.'''
    def __init__(self, parent, datalist, header, *args):
        QTableView.__init__(self, parent, *args)

        self.parent = parent
        self.header = header
        self.mydata = datalist

        self.current = []

        self.model = TableModel(self, self.mydata, self.header)
        self.setModel(self.model)
        self.selectionModel = self.selectionModel()
        self.selectionModel.clearSelection()

        self.nrows = self.model.rowCount(self.model)
        self.ncols = self.model.columnCount(self.model)

        vh = self.verticalHeader()
        vh.setVisible(False)
        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)

        self.cols_resized = [1, 4, 5, 6, 7, 8, 9, 10, 11,
                12, 13, 14, 15, 17]
        for col in self.cols_resized:
            self.resizeColumnToContents(col)
        self.setColumnWidth(1, 250)
        self.setColumnWidth(2, 200)
        self.setColumnWidth(3, 250)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(self.SelectRows)
        self.setSortingEnabled(True)
        # Esconde nome do arquivo.
        self.hideColumn(0)
        # Esconde timestamp.
        self.hideColumn(16)
        self.selecteditems = []

        # Right click
        self.setContextMenuPolicy(Qt.CustomContextMenu)

        # Para limpar entrada dumb na inicialização.
        if self.nrows == 1 and self.mydata[0][0] == '':
            self.model.remove_rows(0, 1, QModelIndex())

        self.connect(self.selectionModel,
                SIGNAL('currentChanged(QModelIndex, QModelIndex)'),
                self.changecurrent)

        self.connect(self.selectionModel,
                SIGNAL('selectionChanged(QItemSelection, QItemSelection)'),
                self.update_selection)

        self.connect(self.model,
                SIGNAL('dataChanged(PyQt_PyObject, PyQt_PyObject, PyQt_PyObject)'),
                self.editmultiple)

        self.connect(self.model,
                SIGNAL('dataChanged(PyQt_PyObject, PyQt_PyObject, PyQt_PyObject)'),
                self.resizecols)

    def editmultiple(self, index, value, oldvalue):
        '''Edita outras linhas selecionadas.'''
        rows = self.selectionModel.selectedRows()
        if len(rows) > 1:
            for row in rows:
                self.selectionModel.clearSelection()
                index = self.model.index(row.row(), index.column(), QModelIndex())
                self.model.setData(index, value, Qt.EditRole)

    def resizecols(self, index):
        '''Ajusta largura das colunas da tabela.'''
        if index.column() in self.cols_resized:
            self.resizeColumnToContents(index.column())

    def outputrows(self, toprow):
        '''Identifica linhas dentro do campo de visão da tabela.'''
        pass
        #TODO Está funcionando, só precisa ver se vale a pena usar...
        #bottomrow = self.verticalHeader().visualIndexAt(self.height())
        #rows = xrange(toprow, bottomrow)
        #for row in rows:
        #    index = self.model.index(row, 0, QModelIndex())
        #    filepath = self.model.data(index, Qt.DisplayRole)
        #    filepath = unicode(filepath.toString())
        #    self.emit(SIGNAL('visibleRow(filepath)'), filepath)

    def emitsaved(self):
        '''Emite aviso que os metadados foram gravados nos arquivos.'''
        self.emit(SIGNAL('savedToFile()'))

    def emitlost(self, filename):
        '''Emite aviso para remover entrada da lista de modificados.'''
        self.emit(SIGNAL('delEntry(PyQt_PyObject)'), filename)

    def update_selection(self, selected, deselected):
        '''Conta entradas selecionadas e atualiza status.'''
        rows = self.selectionModel.selectedRows()
        n_rows = len(rows)
        if n_rows == 1:
            status = u'%d entrada selecionada' % n_rows
        else:
            status = u'%d entradas selecionadas' % n_rows
        self.parent.changeStatus(status)

    def changecurrent(self, current, previous):
        '''Identifica a célula selecionada, extrai valores e envia sinal.

        Os valores são enviados pelo sinal.
        '''
        values = []
        for col in xrange(self.ncols):
            index = self.model.index(current.row(), col, QModelIndex())
            value = self.model.data(index, Qt.DisplayRole)
            values.append((index, value.toString()))
        self.current = values
        self.emit(SIGNAL('thisIsCurrent(PyQt_PyObject)'), values)


class TableModel(QAbstractTableModel):
    '''Modelo dos dados.'''
    def __init__(self, parent, mydata, header, *args):
        QAbstractTableModel.__init__(self, parent, *args)
        self.parent = parent
        self.mydata = mydata
        self.header = header

    def rowCount(self, parent):
        '''Conta as linhas.'''
        return len(self.mydata)

    def columnCount(self, parent):
        '''Conta as colunas.'''
        if self.mydata:
            return len(self.mydata[0])
        else:
            return 0

    def data(self, index, role):
        '''Transforma dados brutos em elementos da tabela.'''
        if not index.isValid():
            return QVariant()
        elif role != Qt.DisplayRole and role != Qt.EditRole and \
                role != Qt.BackgroundRole:
            return QVariant()
        return QVariant(self.mydata[index.row()][index.column()])

    def headerData(self, col, orientation, role):
        '''Constrói cabeçalho da tabela.'''
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return QVariant(self.header[col])
        return QVariant()

    def flags(self, index):
        '''Indicadores do estado de cada ítem.'''
        if not index.isValid():
            return Qt.ItemIsEnabled
        return QAbstractItemModel.flags(self, index) | Qt.ItemIsEditable

    def setData(self, index, value, role):
        '''Salva alterações nos dados a partir da edição da tabela.'''
        if index.isValid() and role == Qt.EditRole:
            oldvalue = self.mydata[index.row()][index.column()]
            # Manter lower case na coluna dos marcadores
            if index.column() == 2:
                #XXX Meio tosco chamar paidopai, mas está funcionando...
                self.mydata[index.row()][index.column()] = self.parent.parent.put_dot(value.toString())
            elif index.column() == 3:
                self.mydata[index.row()][index.column()] = unicode(
                        value.toString()).lower()
            else:
                self.mydata[index.row()][index.column()] = value.toString()
            self.emit(SIGNAL('dataChanged(PyQt_PyObject, PyQt_PyObject, PyQt_PyObject)'),
                    index, value, oldvalue)
            return True
        return False

    def sort(self, col, order):
        '''Ordena entradas a partir de valores de determinada coluna'''
        self.emit(SIGNAL('layoutAboutToBeChanged()'))
        self.mydata = sorted(self.mydata, key=operator.itemgetter(col))
        if order == Qt.DescendingOrder:
            self.mydata.reverse()
        self.emit(SIGNAL('layoutChanged()'))

    def insert_rows(self, position, rows, parent, entry):
        '''Insere entrada na tabela.'''
        self.beginInsertRows(parent, position, position + rows - 1)
        for row in xrange(rows):
            self.mydata.append(entry)
        self.endInsertRows()
        return True

    def remove_rows(self, position, rows, parent):
        '''Remove entrada da tabela.'''
        self.beginRemoveRows(parent, position, position + rows - 1)
        for row in xrange(rows):
            self.mydata.pop(position)
        self.endRemoveRows()
        return True


class DockEditor(QWidget):
    '''Dock com campos para edição dos metadados.'''
    def __init__(self, parent):
        QWidget.__init__(self, parent)

        # varnames tem que bater com o varEdits da vida.
        varnames = [
                ['title', 'caption', 'tags', 'size'],
                ['taxon', 'source', 'author', 'rights'],
                ['location', 'city', 'state', 'country']
                ]
        labels = [
                [u'Título', u'Legenda', u'Marcadores', u'Tamanho'],
                [u'Táxon', u'Especialista', u'Autor', u'Direitos'],
                [u'Local', u'Cidade', u'Estado', u'País']
                ]
        self.sizes = [
                '',
                '<0,1 mm',
                '0,1 - 1,0 mm',
                '1,0 - 10 mm',
                '10 - 100 mm',
                '>100 mm'
                ]

        self.parent = parent

        self.changeStatus = parent.changeStatus

        self.hbox = QHBoxLayout()
        self.setLayout(self.hbox)

        # Tagcompleter: Cria instância do autocompletador de tags
        self.tageditor = CompleterLineEdit(QLineEdit)
        self.tagcompleter = TagCompleter(self.parent.automodels.tags,
                self.tageditor)
        self.tagcompleter.setCaseSensitivity(Qt.CaseInsensitive)
        self.tagcompleter.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.tagcompleter.setModelSorting(QCompleter.CaseInsensitivelySortedModel)

        # Loop para gerar campos de edição.
        #XXX Não sei se vale a pena o trabalho...
        e = 'Edit'
        for box in varnames:
            box_index = varnames.index(box)
            box_layid = 'form' + str(box_index)
            box_id = 'wid' + str(box_index)
            setattr(self, box_layid, QFormLayout())
            setattr(self, box_id, QWidget())
            for var in box:
                var_index = box.index(var)
                setattr(self, var, QLabel('&' + labels[box_index][var_index] + ':'))
                if var == 'size':
                    setattr(self, var + e, QComboBox())
                    eval('self.' + var + e + '.addItems(self.sizes)')
                elif var == 'tags':
                    setattr(self, var + e, self.tageditor)
                else:
                    setattr(self, var + e, QLineEdit())
                # Cria instância dos objetos
                label = eval('self.' + var)
                edit = eval('self.' + var + e)
                label.setBuddy(edit)
                # Dá nome aos objetos, para o live update
                edit.setObjectName(labels[box_index][var_index])
                # Coloca limite de caracteres
                #edit = self.charlimit(edit)
                #TODO Descobrir se os limites são de verdade...
                # Função não funciona tem q aplicar direto aqui.
                if var == 'size':
                    self.connect(edit,
                            SIGNAL('activated(QString)'),
                            self.parent.runtimer)
                else:
                    self.connect(edit,
                            SIGNAL('textEdited(QString)'),
                            self.parent.runtimer)
                if box_index == 0:
                    self.form0.addRow(label, edit)
                elif box_index == 1:
                    self.form1.addRow(label, edit)
                elif box_index == 2:
                    self.form2.addRow(label, edit)
            eval('self.' + box_id + '.setLayout(self.' + box_layid + ')')
            self.hbox.addWidget(eval('self.' + box_id))

        # Inicia valores para o autocomplete
        self.autolistgen(parent.automodels)

        self.setMaximumHeight(150)

        self.connect(mainWidget,
                SIGNAL('thisIsCurrent(PyQt_PyObject)'),
                self.setcurrent)

        self.connect(mainWidget.model,
                SIGNAL('dataChanged(PyQt_PyObject, PyQt_PyObject, PyQt_PyObject)'),
                self.setsingle)

        self.connect(options,
                SIGNAL('rebuildcomplete(PyQt_PyObject)'),
                self.autolistgen)

        self.connect(self.tageditor,
                SIGNAL('text_changed(PyQt_PyObject, PyQt_PyObject)'),
                self.tagcompleter.update)

        self.connect(self.tagcompleter,
                SIGNAL('activated(QString)'),
                self.tageditor.complete_text)

        self.connect(self.tageditor,
                SIGNAL('tagLive(QString)'),
                self.parent.finish)

    def charlimit(self, field):
        '''Limita número de caracteres de acordo com o IPTC.'''
        #TODO Talvez não use essa função.
        if field == u'Título':
            field.setMaxLength(64)
        elif field == u'Legenda':
            field.setMaxLength(2000)
        elif field == u'Táxon':
            field.setMaxLength(256)
        elif field == u'Autor':
            field.setMaxLength(32)
        elif field == u'Especialista':
            field.setMaxLength(32)
        elif field == u'Direitos':
            field.setMaxLength(128)
        elif field == u'Local':
            field.setMaxLength(32)
        elif field == u'Cidade':
            field.setMaxLength(32)
        elif field == u'Estado':
            field.setMaxLength(32)
        elif field == u'País':
            field.setMaxLength(64)
        return field

    def autolistgen(self, models):
        '''Gera autocompletadores dos campos.'''
        self.tagcompleter.setWidget(self.tageditor)

        # Envia texto autocompletado para poder ser salvo no savedata.
        self.completer = MainCompleter(models.taxa, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.taxonEdit.setCompleter(self.completer)

        self.completer = MainCompleter(models.sources, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.sourceEdit.setCompleter(self.completer)

        self.completer = MainCompleter(models.authors, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.authorEdit.setCompleter(self.completer)

        self.completer = MainCompleter(models.rights, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.rightsEdit.setCompleter(self.completer)

        self.completer = MainCompleter(models.places, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.locationEdit.setCompleter(self.completer)

        self.completer = MainCompleter(models.cities, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.cityEdit.setCompleter(self.completer)

        self.completer = MainCompleter(models.states, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.stateEdit.setCompleter(self.completer)

        self.completer = MainCompleter(models.countries, self)
        self.connect(self.completer, SIGNAL('activated(QString)'),
                self.parent.finish)
        self.countryEdit.setCompleter(self.completer)

    def setsingle(self, index, value, oldvalue):
        '''Atualiza campo de edição correspondente quando dado é alterado.'''
        if index.column() == 1:
            self.titleEdit.setText(value.toString())
        elif index.column() == 2:
            self.captionEdit.setText(self.parent.put_dot(value.toString()))
        elif index.column() == 3:
            self.tagsEdit.setText(value.toString())
        elif index.column() == 4:
            self.taxonEdit.setText(value.toString())
        elif index.column() == 5:
            self.sourceEdit.setText(value.toString())
        elif index.column() == 6:
            self.authorEdit.setText(value.toString())
        elif index.column() == 7:
            self.rightsEdit.setText(value.toString())
        elif index.column() == 8:
            for interval in self.sizes:
                if value.toString() == interval:
                    idx = self.sizes.index(interval)
                    self.sizeEdit.setCurrentIndex(idx)
                else:
                    pass
        elif index.column() == 9:
            self.locationEdit.setText(value.toString())
        elif index.column() == 10:
            self.cityEdit.setText(value.toString())
        elif index.column() == 11:
            self.stateEdit.setText(value.toString())
        elif index.column() == 12:
            self.countryEdit.setText(value.toString())

    def setcurrent(self, values):
        '''Atualiza campos de edição quando entrada é selecionada na tabela.'''
        if values:
            self.titleEdit.setText(values[1][1])
            self.captionEdit.setText(values[2][1])
            self.tagsEdit.setText(values[3][1])
            self.taxonEdit.setText(values[4][1])
            self.sourceEdit.setText(values[5][1])
            self.authorEdit.setText(values[6][1])
            self.rightsEdit.setText(values[7][1])
            for interval in self.sizes:
                if values[8][1] == interval:
                    idx = self.sizes.index(interval)
                    self.sizeEdit.setCurrentIndex(idx)
                else:
                    pass
            self.locationEdit.setText(values[9][1])
            self.cityEdit.setText(values[10][1])
            self.stateEdit.setText(values[11][1])
            self.countryEdit.setText(values[12][1])
            self.values = values


class AutoModels():
    '''Cria modelos para autocompletar campos de edição.'''
    def __init__(self, ilist):
        self.autolists = ilist
        for k, v in self.autolists.iteritems():
            if v:
                v.sort()
                setattr(self, k, QStringListModel(v))
            else:
                setattr(self, k, QStringListModel())


class MainCompleter(QCompleter):
    '''Autocomplete principal.'''
    def __init__(self, model, parent):
        QCompleter.__init__(self, model, parent)

        self.setModel(model)
        self.setCaseSensitivity(Qt.CaseInsensitive)
        self.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self.setModelSorting(QCompleter.CaseInsensitivelySortedModel)


class TagCompleter(QCompleter):
    '''Completador de marcadores.

    Adaptado de John Schember:
    john.nachtimwald.com/2009/07/04/qcompleter-and-comma-separated-tags/
    '''
    def __init__(self, model, parent):
        QCompleter.__init__(self, model, parent)
        self.model = model

    def update(self, text_tags, completion_prefix):
        #tags = self.list.difference(text_tags)
        #model = QStringListModel(tags, self)
        self.setModel(self.model)

        self.setCompletionPrefix(completion_prefix)
        if completion_prefix.strip() != '':
            self.complete()


class CompleterLineEdit(QLineEdit):
    '''Editor especial para marcadores.

    Adaptado de John Schember:
    john.nachtimwald.com/2009/07/04/qcompleter-and-comma-separated-tags/
    '''
    def __init__(self, *args):
        QLineEdit.__init__(self)
        self.connect(self, SIGNAL('textEdited(QString)'), self.text_changed)

    def text_changed(self, text):
        all_text = unicode(text)
        text = all_text[:self.cursorPosition()]
        prefix = text.split(',')[-1].strip()

        text_tags = []
        for t in all_text.split(','):
            t1 = unicode(t).strip()
            if t1 != '':
                text_tags.append(t)
        text_tags = list(set(text_tags))

        self.emit(SIGNAL('text_changed(PyQt_PyObject, PyQt_PyObject)'),
            text_tags, prefix)

    def complete_text(self, text):
        cursor_pos = self.cursorPosition()
        before_text = unicode(self.text())[:cursor_pos]
        after_text = unicode(self.text())[cursor_pos:]
        prefix_len = len(before_text.split(',')[-1].strip())
        self.setText('%s%s, %s' % (before_text[:cursor_pos - prefix_len], text,
            after_text))
        self.setCursorPosition(cursor_pos - prefix_len + len(text) + 2)
        self.emit(SIGNAL('tagLive(QString)'), self.text())


class ChromePage(QWebPage):
    '''Dummy class for GMaps dragging bug (Issue #24).'''
    def userAgentForUrl(self, url):
        return 'Chrome/1.0'


class DockGeo(QWidget):
    '''Dock para editar a geolocalização da imagem.'''
    def __init__(self, parent):
        QWidget.__init__(self, parent)

        self.changeStatus = parent.changeStatus
        self.parent = parent

        # Layout do dock
        self.hbox = QHBoxLayout()

        # Editor
        self.lat_label = QLabel(u'Latitude:')
        self.lat = QLineEdit()
        self.lat.setObjectName(u'Latitude')
        self.long_label = QLabel(u'Longitude:')
        self.long = QLineEdit()
        self.long.setObjectName(u'Longitude')
        self.updatebutton = QPushButton(u'&Atualizar', self)

        # Mask e validator
        #TODO Melhorar as regex...
        # LAT
        self.lat.setInputMask(u'>A 99°99\'99";_')
        lat_rx = QRegExp(u'^[N,S]( )\d\d(°)([0-6][0-9])(\')([0-6][0-9])(")$')
        lat_validator = QRegExpValidator(lat_rx, self)
        self.lat.setValidator(lat_validator)
        # LONG
        self.long.setInputMask(u'>A 099°99\'99";_')
        long_rx = QRegExp(u'^[W,E]( )\d?\d\d(°)([0-6][0-9])(\')([0-6][0-9])(")$')
        long_validator = QRegExpValidator(long_rx, self)
        self.long.setValidator(long_validator)

        # Layout do Editor
        self.editbox = QFormLayout()
        self.editbox.addRow(self.lat_label, self.lat)
        self.editbox.addRow(self.long_label, self.long)
        self.editbox.addRow(self.updatebutton)

        # Widgets do Dock
        self.geolocation = QWidget()
        self.geolocation.setLayout(self.editbox)
        self.map = QWebView(self)
        self.map.setPage(ChromePage())

        # Tamanhos
        self.geolocation.setFixedWidth(200)
        self.map.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Layout do Dock
        self.hbox.addWidget(self.geolocation)
        self.hbox.addWidget(self.map)
        self.setLayout(self.hbox)

        self.connect(self.updatebutton,
                SIGNAL('clicked()'),
                self.update_geo)

        self.connect(mainWidget,
                SIGNAL('thisIsCurrent(PyQt_PyObject)'),
                self.setcurrent)

        self.connect(mainWidget.model,
                SIGNAL('dataChanged(PyQt_PyObject, PyQt_PyObject, PyQt_PyObject)'),
                self.setsingle)

        self.connect(self.parent,
                SIGNAL('mapVisibility(PyQt_PyObject)'),
                self.state)

        # Live update
        self.connect(self.lat,
                SIGNAL('textEdited(QString)'),
                self.parent.runtimer)

        self.connect(self.long,
                SIGNAL('textEdited(QString)'),
                self.parent.runtimer)

    def state(self, visible):
        '''Relata se aba está visível e/ou selecionada.

        Captura sinal emitido pelo geoDockWidget. Se estiver visível ou
        selecionado, carrega mapa usando coordenadas dos campos self.lat e
        self.long, definidos na função setcurrent.
        '''
        self.ismap_selected = visible
        latitude = self.lat.text()
        longitude = self.long.text()
        if latitude.startsWith('N') or latitude.startsWith('S'):
            lat = True
        if longitude.startsWith('W') or longitude.startsWith('E'):
            long = True
        try:
            if visible and lat and long:
                # Se estiver visível, carregar o mapa.
                self.load_geocode(latitude, longitude)
        except:
            logger.debug('Sem GPS.')

    def gps_string(self, gps):
        '''Transforma coordenadas extraídas do exif em texto.'''
        dms_str = {}
        dms_str['lat'] = u'%s %02d°%02d\'%02d"' % (
                gps['latref'], gps['latdeg'],
                gps['latmin'], gps['latsec'])
        dms_str['long'] = u'%s %03d°%02d\'%02d"' % (
                gps['longref'], gps['longdeg'],
                gps['longmin'], gps['longsec'])
        return dms_str

    def setdms(self, dms):
        '''Atualiza as coordenadas do editor e da tabela.'''
        dms_str = self.gps_string(dms)
        self.lat.setText(dms_str['lat'])
        self.parent.savedata(self.lat, '')
        self.long.setText(dms_str['long'])
        self.parent.savedata(self.long, '')

    def update_geo(self):
        '''Captura as coordenadas do marcador para atualizar o editor.'''
        # Captura coordenadas do último marcador do mapa.
        mark = self.map.page().mainFrame().evaluateJavaScript(
                'document.getElementById("markerlocation").value').toString()
        # Transforma a string em lista com floats, limpando os parenteses.
        if mark:
            marker = str(mark).strip('()').split(', ')
            decimals = [float(c) for c in marker]
            # Converte decimal para sistema de coordenadas
            dms = self.un_decimal(decimals[0], decimals[1])
            self.setdms(dms)
        else:
            logger.info('Nenhum ponto está marcado no mapa.')

    def un_decimal(self, lat, long):
        '''Converte o valor decimal das coordenadas.

        Retorna dicionário com referência cardinal, graus, minutos e segundos.
        '''
        # Latitude
        latdeg = int(abs(lat))
        latmin = (abs(lat) - latdeg) * 60
        latsec = int((latmin - int(latmin)) * 60)
        latmin = int(latmin)

        # Longitude
        longdeg = int(abs(long))
        longmin = (abs(long) - longdeg) * 60
        longsec = int((longmin - int(longmin)) * 60)
        longmin = int(longmin)

        # Cardinals
        if lat < 0:
            latref = 'S'
        else:
            latref = 'N'
        if long < 0:
            longref = 'W'
        else:
            longref = 'E'

        dms = {
                'latref': latref,
                'latdeg': latdeg,
                'latmin': latmin,
                'latsec': latsec,
                'longref': longref,
                'longdeg': longdeg,
                'longmin': longmin,
                'longsec': longsec,
                }

        return dms

    def write_html(self, unset=0, lat=0.0, long=0.0, zoom=9):
        '''Carrega código HTML da QWebView com mapa do Google Maps.

        Usando o API V3.
        '''
        self.map.setHtml('''
        <html>
        <head>
        <meta name="viewport" content="initial-scale=1.0, user-scalable=no" />
        <meta http-equiv="content-type" content="text/html; charset=UTF-8"/>
        <title>Véliger</title>
        <script type="text/javascript" src="http://maps.google.com/maps/api/js?v=3.1&sensor=false&language=pt-BR"></script>
        <script type="text/javascript">
            if ('ontouchstart' in document.documentElement) {
                // window.alert("No touch support!");
                document.documentElement.ontouchstart = null;
            }
            var map;
            var marker;
            function initialize() {
                var unset = %d;
                var local = new google.maps.LatLng(%f,%f);
                var myOptions = {
                    zoom: %d,
                    center: local,
                    mapTypeId: google.maps.MapTypeId.ROADMAP,
                    draggable: true,
                    keyboardShortcuts: true,
                    mapTypeControl: true,
                    navigationControl: true,
                    scrollwheel: true,
                    disableDoubleClickZoom: false,
                    streetViewControl: false,
                }

                map = new google.maps.Map(document.getElementById("map_canvas"), myOptions);

                if (unset == 0) {
                    var marker = new google.maps.Marker({
                        position: local,
                        map: map,
                        title:"Local",
                        draggable: true,
                    });
                    document.getElementById("markerlocation").value = marker.position;
                }
                else {
                    google.maps.event.addListener(map, 'rightclick', function(event) {
                        placeMarker(event.latLng);
                    });
                }

                google.maps.event.addListener(marker, 'dragend', function() {
                    document.getElementById("markerlocation").value = marker.position;
                    map.setCenter(marker.position);
                });
            }

            function placeMarker(location) {
                var clickedLocation = new google.maps.LatLng(location);

                var marker = new google.maps.Marker({
                    position: location,
                    map: map,
                    draggable: true,
                });

                document.getElementById("markerlocation").value =
                marker.position;

                map.setCenter(location);
                map.setZoom(5);

                google.maps.event.addListener(marker, 'dragend', function() {
                    document.getElementById("markerlocation").value = marker.position;
                    map.setCenter(marker.position);
                });

            }

        </script>
        </head>
        <body style="margin:0px; padding:0px;" onload="initialize()">
            <div id="map_canvas" style="width: 100%%; height: 100%%;"></div>
            <input id="markerlocation" type="hidden" />
        </body>
        </html>
        ''' % (unset, lat, long, zoom))

    def load_geocode(self, lat, long):
        '''Pega string das coordenadas e chama mapa com as variáveis correspondentes.'''
        # Se uma coordenada estiver vazia, não carregar.
        if len(lat) > 4 and len(long) > 4:
            gps = self.string_gps(lat, long)
            # Cria valores decimais das coordenadas
            self.lat_dec = self.get_decimal(
                    gps['latref'], gps['latdeg'],
                    gps['latmin'], gps['latsec'])
            self.long_dec = self.get_decimal(
                    gps['longref'], gps['longdeg'],
                    gps['longmin'], gps['longsec'])
            self.write_html(lat=self.lat_dec, long=self.long_dec)
        else:
            # Imagem sem coordenadas
            self.write_html(unset=1, zoom=1)

    def get_exif(self, filepath):
        '''Extrai o exif da imagem selecionada usando o pyexiv2 0.3.0.'''
        exif_meta = pyexiv2.ImageMetadata(unicode(filepath))
        exif_meta.read()
        return exif_meta

    def get_gps(self, exif_meta):
        '''Extrai gps do exif.'''
        gps = {}
        try:
            gps['latref'] = exif_meta['Exif.GPSInfo.GPSLatitudeRef'].value
            gps['latdeg'] = exif_meta['Exif.GPSInfo.GPSLatitude'].value[0]
            gps['latmin'] = exif_meta['Exif.GPSInfo.GPSLatitude'].value[1]
            gps['latsec'] = exif_meta['Exif.GPSInfo.GPSLatitude'].value[2]
            gps['longref'] = exif_meta['Exif.GPSInfo.GPSLongitudeRef'].value
            gps['longdeg'] = exif_meta['Exif.GPSInfo.GPSLongitude'].value[0]
            gps['longmin'] = exif_meta['Exif.GPSInfo.GPSLongitude'].value[1]
            gps['longsec'] = exif_meta['Exif.GPSInfo.GPSLongitude'].value[2]
            return gps
        except:
            return gps

    def get_date(self, exif):
        '''Extrai a data em que foi criada a foto do EXIF.'''
        try:
            date = exif['Exif.Photo.DateTimeOriginal']
        except:
            try:
                date = exif['Exif.Photo.DateTimeDigitized']
            except:
                try:
                    date = exif['Exif.Image.DateTime']
                except:
                    return False
        return date.value

    def resolve(self, frac):
        '''Resolve a fração das coordenadas para int.

        Por padrão os valores do exif são guardados como frações. Por isso é
        necessário converter.
        '''
        fraclist = str(frac).split('/')
        result = int(fraclist[0]) / int(fraclist[1])
        return result

    def setsingle(self, index, value, oldvalue):
        '''Atualiza campo de edição correspondente quando tabela é alterada.'''
        if index.column() == 13:
            self.lat.setText(value.toString())
        elif index.column() == 14:
            self.long.setText(value.toString())
        if self.ismap_selected:
            self.load_geocode(self.lat.text(), self.long.text())

    def setcurrent(self, values):
        '''Mostra geolocalização da imagem selecionada.

        Os valores texto devem ser importados mesmo com o widget escondido para
        serem acessados pela função state. E assim carregar o mapa quando a
        imagem já estiver selecionada e a aba tornar-se visível.
        '''
        latitude = values[13][1]
        longitude = values[14][1]
        if latitude and longitude:
            self.lat.setText(latitude)
            self.long.setText(longitude)
        else:
            self.lat.setText('')
            self.long.setText('')
        # Se o dock estiver visível, carregar o mapa.
        if self.ismap_selected:
            self.load_geocode(latitude, longitude)
        else:
            # Só vai aparecer se ocorrer algum erro no load_geocode.
            self.map.setHtml('''<html><head></head><body><h1>Clique na entrada novamente...</h1></body></html>''')

    def string_gps(self, latitude, longitude):
        '''Converte string das coordenadas para dicionário.'''
        lat = re.findall('\w+', latitude)
        long = re.findall('\w+', longitude)
        gps = {
                'latref': lat[0],
                'latdeg': int(lat[1]),
                'latmin': int(lat[2]),
                'latsec': int(lat[3]),
                'longref': long[0],
                'longdeg': int(long[1]),
                'longmin': int(long[2]),
                'longsec': int(long[3]),
                }
        return gps

    def get_decimal(self, ref, deg, min, sec):
        '''Descobre o valor decimal das coordenadas.'''
        decimal_min = (min * 60.0 + sec) / 60.0
        decimal = (deg * 60.0 + decimal_min) / 60.0
        negs = ['S', 'W']
        if ref in negs:
            decimal = -decimal
        return decimal

    def geodict(self, latitude, longitude):
        '''Extrai coordenadas da string do editor.

        Transforma string em dicionário para ser gravado na imagem. Exif aceita
        os valores numéricos apenas como razões.'''
        # Utiliza expressões regulares.
        lat = re.findall('\w+', latitude)
        long = re.findall('\w+', longitude)
        gps = {
                'latref': lat[0],
                'latdeg': pyexiv2.utils.Rational(lat[1], 1),
                'latmin': pyexiv2.utils.Rational(lat[2], 1),
                'latsec': pyexiv2.utils.Rational(lat[3], 1),
                'longref': long[0],
                'longdeg': pyexiv2.utils.Rational(long[1], 1),
                'longmin': pyexiv2.utils.Rational(long[2], 1),
                'longsec': pyexiv2.utils.Rational(long[3], 1),
                }
        return gps


class RefsTable(QTableView):
    '''Tabela com referências bibliográficas'''
    def __init__(self, datalist, header, *args):
        QTableView.__init__(self, *args)

        self.header = header
        self.mydata = datalist

        self.current = []

        self.model = TableModel(self, self.mydata, self.header)
        self.setModel(self.model)
        self.selectionModel = self.selectionModel()
        self.selectionModel.clearSelection()

        self.nrows = self.model.rowCount(self.model)
        self.ncols = self.model.columnCount(self.model)

        vh = self.verticalHeader()
        vh.setVisible(False)
        hh = self.horizontalHeader()
        hh.setStretchLastSection(True)

        self.cols_resized = [0, 1, 2, 4, 5, 6, 7]
        for col in self.cols_resized:
            self.resizeColumnToContents(col)
        self.setColumnWidth(2, 200)
        self.setColumnWidth(3, 250)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(self.SelectRows)
        self.setSortingEnabled(True)
        self.selecteditems = []

        # Para limpar entrada dumb na inicialização.
        if self.nrows == 1 and self.mydata[0][0] == '':
            self.model.remove_rows(0, 1, QModelIndex())


class DockRefs(QWidget):
    '''Exibe lista de referências.'''
    def __init__(self, parent):
        QWidget.__init__(self, parent)

        self.header = [u'ID', u'Ano', u'Autores', u'Título', u'Revista',
                u'Volume', u'Número', u'Páginas']

        self.parent = parent

        self.mylist = refslist

        self.view = QTableView()
        self.model = TableModel(self, self.mylist, self.header)

        self.view.setModel(self.model)
        self.view.selectionModel = self.view.selectionModel()
        self.view.selectionModel.clearSelection()

        self.nrows = self.model.rowCount(self.model)
        self.ncols = self.model.columnCount(self.model)

        vh = self.view.verticalHeader()
        vh.setVisible(False)
        hh = self.view.horizontalHeader()
        hh.setStretchLastSection(True)

        self.view.cols_resized = [0, 1, 2, 4, 5, 6, 7]
        for col in self.view.cols_resized:
            self.view.resizeColumnToContents(col)
        self.view.setColumnWidth(2, 300)
        self.view.setColumnWidth(3, 450)
        self.view.setAlternatingRowColors(True)
        self.view.setSelectionBehavior(self.view.SelectRows)
        self.view.setSortingEnabled(True)
        self.selecteditems = []

        # Para limpar entrada dumb na inicialização.
        #if self.nrows == 1 and self.model.mydata[0][0] == '':
        #    self.view.model.remove_rows(0, 1, QModelIndex())

        # Usando uma instância própria da view:
        #self.view = RefsTable(self.mylist, self.header)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.upbutton = QPushButton(u'&Aplicar', self)
        self.syncbutton = QPushButton(u'&Mendeley Sync', self)

        self.vbox = QVBoxLayout()
        self.vbox.addWidget(self.upbutton)
        self.vbox.addWidget(self.syncbutton)
        self.buttons = QWidget()
        self.buttons.setLayout(self.vbox)

        self.hbox = QHBoxLayout()
        self.hbox.addWidget(self.view)
        self.hbox.addWidget(self.buttons)
        self.setLayout(self.hbox)

        self.connect(self.upbutton,
                SIGNAL('clicked()'),
                self.update)

        self.connect(self.syncbutton,
                SIGNAL('clicked()'),
                self.sync_references)

        self.connect(mainWidget,
                SIGNAL('delEntry(PyQt_PyObject)'),
                self.lostentry)

    def update(self):
        '''Aplica referências selecionadas para as entradas selecionadas.'''
        indexes = self.view.selectedIndexes()
        total = []
        if indexes:
            for index in indexes:
                if index.column() == 0:
                    total.append(str(self.model.data(index,
                        Qt.DisplayRole).toString()))
        self.emit(SIGNAL('refSync(PyQt_PyObject)'), total)

    def get_mendeley(self):
        '''Cria instância para o cliente do Mendeley.'''
        try:
            mendeley = Mendeley()
            return mendeley
        except:
            logger.warning('Erro ao criar cliente do Mendeley.')
            return None

    def parse_references(self, documents_details):
        '''Parse dictionary with documents details from Mendeley.'''
        try:
            keys = ['year', 'authors', 'title', 'publication_outlet', 'volume',
                    'issue', 'pages']
            document_list = []
            for k, v in documents_details.iteritems():
                # Checa se key existe antes para evitar erros.
                for key in keys:
                    if not key in v:
                        v[key] = ''
                # Processa autores.
                authors = ', '.join([a['surname'] for a in v['authors']])
                entry = [k, v['year'], authors, v['title'],
                        v['publication_outlet'], v['volume'], v['issue'],
                        v['pages']]
                document_list.append(entry)
            return document_list
        except:
            logger.warning('Ocorreu erro no parsing de alguma referência.')
            return None

    def sync_references(self):
        '''Acessa coleção de referências remota e refaz a lista.'''
        self.parent.changeStatus(u'Conectando ao Mendeley, aguarde...', 5000)
        mendeley = self.get_mendeley()
        logger.debug('Conectado ao Mendeley, processando documentos.')
        document_list = self.parse_references(mendeley.documents_details)
        total_results = mendeley.total_results
        self.clearlist()
        try:
            for citation in document_list:
                self.model.insert_rows(0, 1, QModelIndex(), citation)
            self.parent.changeStatus(u'%s referências carregadas com sucesso do Mendeley.' % total_results, 5000)
            logger.info('%s referências carregadas do Mendeley.',
                    total_results)
        except:
            self.parent.changeStatus(u'Erro para inserir referências na tabela.', 5000)
            logger.warning('Erro para inserir referências na tabela.')

    def insertentry(self, index, value, oldvalue):
        '''Insere entrada na lista.

        Checa se a modificação não foi nula (valor atual == valor anterior) e
        se a entrada é duplicada.
        '''
        if value == oldvalue:
            pass
        else:
            index = mainWidget.model.index(index.row(), 0, QModelIndex())
            filepath = mainWidget.model.data(index, Qt.DisplayRole)
            filename = os.path.basename(unicode(filepath.toString()))
            matches = self.matchfinder(filename)
            if len(matches) == 0:
                self.model.insert_rows(0, 1, QModelIndex(), filename)
            else:
                pass

    def lostentry(self, bibkey):
        '''Avisa sobre referência perdida.'''
        logger.warning('Referência não está no banco de dados: bibkey')
        #matches = self.matchfinder(filename)
        #if len(matches) == 1:
        #    match = matches[0]
        #    self.model.remove_rows(match.row(), 1, QModelIndex())

    def clearlist(self):
        '''Remove todas as entradas da lista.'''
        rows = self.model.rowCount(self.view.model)
        if rows > 0:
            self.model.remove_rows(0, rows, QModelIndex())
        else:
            self.parent.changeStatus(u'Nada pra deletar.')

    def matchfinder(self, candidate):
        '''Buscador de duplicatas exatas.'''
        index = self.model.index(0, 0, QModelIndex())
        matches = self.model.match(index, 0, candidate, -1, Qt.MatchExactly)
        return matches

    def resizeEvent(self, event):
        '''Lida com redimensionamentos.'''
        event.accept()


class UserFilter(QObject):
    '''Filtro para identificar edições do usuário.

    Intercepta teclas apertadas e botão do meio do mouse e interpreta como
    edição do usuário; redefine estado do objeto.
    '''
    def __init__(self, parent):
        QObject.__init__(self, parent)
        self.parent = parent

    def eventFilter(self, object, event):
        if event.type() == QEvent.KeyPress or event.type() == QEvent.Wheel:
            self.parent.edited = True
        else:
            pass
        return False


class DockThumb(QWidget):
    '''Dock para mostrar o thumbnail da imagem selecionada.'''
    def __init__(self, parent):
        QWidget.__init__(self, parent)

        self.parent = parent

        self.edited = False

        self.setMaximumWidth(300)

        # Layout do dock
        self.vbox = QVBoxLayout()

        # Thumb
        self.pic = QPixmap()
        self.thumb = QLabel()

        # Informações do arquivo
        self.filename_label = QLabel(u'Arquivo:')
        self.filename = QLabel()
        self.timestamp_label = QLabel(u'Timestamp:')
        self.timestamp = QLabel()
        # DateTimeEdit
        self.dateedit_label = QLabel(u'Criação:')
        self.dateedit = QDateTimeEdit(self)
        self.dateedit.setDisplayFormat('yyyy-MM-dd hh:mm:ss')
        self.dateedit.setObjectName(u'Data')

        self.userfilter = UserFilter(self)
        self.dateedit.installEventFilter(self.userfilter)

        self.thumb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.thumb.setMaximumWidth(300)
        self.thumb.setMinimumSize(100, 100)
        self.thumb.setAlignment(Qt.AlignHCenter)

        # Layout do Editor
        self.infobox = QFormLayout()
        self.infobox.addRow(self.filename_label, self.filename)
        self.infobox.addRow(self.timestamp_label, self.timestamp)
        self.infobox.addRow(self.dateedit_label, self.dateedit)

        # Widget das informações
        self.fileinfo = QWidget()
        self.fileinfo.setLayout(self.infobox)

        # Adicionando widgets ao dock
        self.vbox.addWidget(self.thumb)
        self.vbox.addWidget(self.fileinfo)
        self.vbox.addStretch(1)

        self.filename.setWordWrap(True)
        self.setLayout(self.vbox)

        QPixmapCache.setCacheLimit(81920)

        self.connect(mainWidget,
                SIGNAL('thisIsCurrent(PyQt_PyObject)'),
                self.setcurrent)

        self.connect(mainWidget,
                SIGNAL('visibleRow(PyQt_PyObject)'),
                self.pixmapcache)

        self.connect(mainWidget.model,
                SIGNAL('dataChanged(PyQt_PyObject, PyQt_PyObject, PyQt_PyObject)'),
                self.setsingle)

        # Live update
        self.connect(self.dateedit,
                SIGNAL('dateTimeChanged(QDateTime)'),
                self.edited_or_not)

    def edited_or_not(self):
        '''Descobre se o campo foi editado pelo usuário ou não.

        Desencadeia o processo de salvar caso a mudança tenha se originado do
        usuário.'''
        if self.edited:
            self.parent.runtimer()
        else:
            pass

    def iodate(self, mydate=False):
        '''Retorna data atual como string ou QDateTime; ou data padrão.

        Depende do input.
        '''
        default_date = QDateTime.fromString(
                '1900-01-01 00:00:00', 'yyyy-MM-dd hh:mm:ss')
        if mydate:
            # QVariant.String == 10
            if isinstance(mydate, str) or QVariant(mydate).type() == 10:
                current_date = QDateTime.fromString(mydate, 'yyyy-MM-dd hh:mm:ss')
                if current_date.isValid():
                    return current_date
                else:
                    logger.warning('Formato da data inválido! Corrigir.')
                    self.parent.changeStatus(
                            u'Formato da data inválido! Corrigir na tabela ou usar o campo de edição.', 8000)
                    return default_date
            else:
                current_date = mydate.toString('yyyy-MM-dd hh:mm:ss')
                return current_date
        else:
            return default_date

    def setsingle(self, index, value, oldvalue):
        '''Atualiza campo de edição quando tabela é alterada diretamente.'''
        if index.column() == 15:
            current_date = QDateTime.fromString(value.toString(), 'yyyy-MM-dd hh:mm:ss')
            default_date = QDateTime.fromString('1900-01-01 00:00:00', 'yyyy-MM-dd hh:mm:ss')
            if value.toString():
                self.dateedit.setDateTime(self.iodate(value.toString()))
            else:
                self.dateedit.setDateTime(self.iodate())

    def pixmapcache(self, filepath):
        '''Cria cache para thumbnail.'''
        filename = os.path.basename(unicode(filepath))
        thumbpath = os.path.join(thumbdir, filename)
        # Tenta abrir o cache
        if not QPixmapCache.find(filename, self.pic):
            self.pic.load(thumbpath)
            QPixmapCache.insert(filename, self.pic)
        else:
            pass
        return self.pic

    def setcurrent(self, values):
        '''Mostra thumbnail, nome e data de modificação da imagem.

        Captura sinal com valores, tenta achar imagem no cache e exibe
        informações.
        '''
        if values and values[0][1] != '':
            file = os.path.basename(unicode(values[0][1]))
            self.filename.setText(unicode(file))
            self.dateedit.setDateTime(self.iodate(values[15][1]))
            timestamp = values[16][1]
            self.timestamp.setText(timestamp)

            # Tenta abrir o cache
            self.pic = self.pixmapcache(values[0][1])
        elif values and values[0][1] == '':
            self.pic = QPixmap()
            self.filename.clear()
            self.dateedit.setDateTime(self.iodate())
            self.timestamp.clear()
            self.thumb.clear()
        else:
            self.pic = QPixmap()
            self.filename.clear()
            self.dateedit.setDateTime(self.iodate())
            self.timestamp.clear()
            self.thumb.clear()
        self.updateThumb()

    def updateThumb(self):
        '''Atualiza thumbnail.'''
        if self.pic.isNull():
            self.thumb.setText(u'Imagem indisponível')
            pass
        else:
            scaledpic = self.pic.scaled(self.width(), self.height() - 65,
                    Qt.KeepAspectRatio, Qt.FastTransformation)
            self.thumb.setPixmap(scaledpic)

    def resizeEvent(self, event):
        '''Lida com redimensionamento do thumbnail.'''
        event.accept()
        self.updateThumb()


class DockUnsaved(QWidget):
    '''Exibe lista com imagens modificadas.

    Utiliza dados do modelo em lista. Qualquer imagem modificada será
    adicionada à lista. Seleção na lista seleciona entrada na tabela. Gravar
    salva metadados de cada ítem da lista nas respectivas imagens.
    '''
    def __init__(self, parent):
        QWidget.__init__(self, parent)

        self.mylist = updatelist
        self.model = ListModel(self, self.mylist)

        self.view = QListView()
        self.view.setModel(self.model)
        self.view.selectionModel = self.view.selectionModel()
        self.view.setAlternatingRowColors(True)

        self.savebutton = QPushButton(u'&Gravar', self)
        if not self.model.mylist:
            self.savebutton.setDisabled(True)

        self.vbox = QVBoxLayout()
        self.vbox.addWidget(self.view)
        self.vbox.addWidget(self.savebutton)
        self.setLayout(self.vbox)

        self.connect(mainWidget.model,
                SIGNAL('dataChanged(PyQt_PyObject, PyQt_PyObject, PyQt_PyObject)'),
                self.insertentry)

        self.connect(self.view.selectionModel,
                SIGNAL('selectionChanged(QItemSelection, QItemSelection)'),
                self.sync_setselection)

        self.connect(self.savebutton,
                SIGNAL('clicked()'),
                parent.commitmeta)

        self.connect(mainWidget,
                SIGNAL('savedToFile()'),
                self.clearlist)

        self.connect(mainWidget,
                SIGNAL('delEntry(PyQt_PyObject)'),
                self.delentry)

    def sync_setselection(self, selected, deselected):
        '''Sincroniza seleção da tabela com a seleção da lista.'''
        indexes = selected.indexes()
        if indexes:
            index = indexes[0]
            filename = self.model.data(index, Qt.DisplayRole)
            filename = filename.toString()
            self.emit(SIGNAL('syncSelection(PyQt_PyObject)'), filename)

    def insertentry(self, index, value, oldvalue):
        '''Insere entrada na lista.

        Checa se a modificação não foi nula (valor atual == valor anterior) e
        se a entrada é duplicada.
        '''
        if value == oldvalue:
            pass
        else:
            index = mainWidget.model.index(index.row(), 0, QModelIndex())
            filepath = mainWidget.model.data(index, Qt.DisplayRole)
            filename = os.path.basename(unicode(filepath.toString()))
            matches = self.matchfinder(filename)
            if len(matches) == 0:
                self.model.insert_rows(0, 1, QModelIndex(), filename)
                self.savebutton.setEnabled(True)
            else:
                pass

    def delentry(self, filename):
        '''Remove entrada da lista.'''
        matches = self.matchfinder(filename)
        if len(matches) == 1:
            match = matches[0]
            self.model.remove_rows(match.row(), 1, QModelIndex())
            if not self.model.mylist:
                self.savebutton.setDisabled(True)

    def clearlist(self):
        '''Remove todas as entradas da lista.'''
        rows = self.model.rowCount(self.model)
        if rows > 0:
            self.model.remove_rows(0, rows, QModelIndex())
            self.savebutton.setDisabled(True)
        else:
            self.parent.changeStatus('Nada pra deletar.')

    def matchfinder(self, candidate):
        '''Buscador de duplicatas.'''
        index = self.model.index(0, 0, QModelIndex())
        matches = self.model.match(index, 0, candidate, -1, Qt.MatchExactly)
        return matches

    def resizeEvent(self, event):
        '''Lida com redimensionamentos.'''
        event.accept()


class ListModel(QAbstractListModel):
    '''Modelo com lista de imagens modificadas e referências.'''
    def __init__(self, parent, list, *args):
        QAbstractListModel.__init__(self, parent, *args)
        self.mylist = list

    def rowCount(self, parent):
        '''Conta linhas.'''
        return len(self.mylist)

    def data(self, index, role):
        '''Cria elementos da lista a partir dos dados.'''
        if not index.isValid():
            return QVariant()
        elif role != Qt.DisplayRole:
            return QVariant()
        return QVariant(self.mylist[index.row()])

    def insert_rows(self, position, rows, parent, entry):
        '''Insere linhas.'''
        self.beginInsertRows(parent, position, position + rows - 1)
        for row in xrange(rows):
            self.mylist.append(entry)
        self.endInsertRows()
        return True

    def remove_rows(self, position, rows, parent):
        '''Remove linhas.'''
        self.beginRemoveRows(parent, position, position + rows - 1)
        for row in xrange(rows):
            self.mylist.pop(position)
        self.endRemoveRows()
        return True


#=== MAIN ===#

def initialize():
    '''Inicia variáveis e parâmetros globais do programa.'''
    global tablepickle
    global refspickle
    global listpickle
    global autopickle
    global header
    global datalist
    global updatelist
    global refslist
    global autolists
    global thumbdir  # global para ser usada no pixmapcache

    thumbdir = 'thumbs'

    # Cabeçalho horizontal da tabela principal
    header = [
            u'Arquivo',       # 0
            u'Título',        # 1
            u'Legenda',       # 2
            u'Marcadores',    # 3
            u'Táxon',         # 4
            u'Especialista',  # 5
            u'Autor',         # 6
            u'Direitos',      # 7
            u'Tamanho',       # 8
            u'Local',         # 9
            u'Cidade',        # 10
            u'Estado',        # 11
            u'País',          # 12
            u'Latitude',      # 13
            u'Longitude',     # 14
            u'Data',          # 15
            u'Timestamp',     # 16
            u'Referências',   # 17
            ]

    # Nome do arquivo Pickle para tabela
    tablepickle = '.tablecache'
    try:
        tablecache = open(tablepickle, 'rb')
        datalist = pickle.load(tablecache)
        tablecache.close()
        if not datalist:
            datalist.append([
                u'', u'', u'', u'', u'',
                u'', u'', u'', u'', u'',
                u'', u'', u'', u'', u'',
                u'', u'', u'',
                ])
    except:
        logger.debug('Arquivo .tablecache não existe, criando novo.')
        f = open(tablepickle, 'wb')
        f.close()
        datalist = [[
            u'', u'', u'', u'', u'',
            u'', u'', u'', u'', u'',
            u'', u'', u'', u'', u'',
            u'', u'', u'',
            ], ]

    # Nome do arquivo Pickle para lista
    listpickle = '.listcache'
    try:
        listcache = open(listpickle, 'rb')
        updatelist = pickle.load(listcache)
        listcache.close()
    except:
        logger.debug('Arquivo .listcache não existe, criando novo.')
        f = open(listpickle, 'wb')
        f.close()
        updatelist = []

    # Nome do arquivo Pickle para lista
    refspickle = '.refscache'
    try:
        refscache = open(refspickle, 'rb')
        refslist = pickle.load(refscache)
        refscache.close()
    except:
        logger.debug('Arquivo .refscache não existe, criando novo.')
        f = open(refspickle, 'wb')
        f.close()
        refslist = [[
            u'', u'', u'', u'',
            u'', u'', u'', u'',
            ], ]

    # Nome do arquivo Pickle para autocomplete
    autopickle = '.autocomplete'
    try:
        logger.info('Conectando ao Cifonauta...')
        connection = urlretrieve('http://cifonauta.cebimar.usp.br/autocomplete.pkl', '.autocomplete')
        logger.info('Autocomplete sincronizado!')
    except:
        logger.debug('Não conseguiu baixar o autocomplete.')
    try:
        autocomplete = open(autopickle, 'rb')
        autolists = pickle.load(autocomplete)
        autocomplete.close()
    except:
        logger.debug('Arquivo .autocomplete não existe, criando novo.')
        f = open(autopickle, 'wb')
        autolists = {
                'tags': [],
                'taxa': [],
                'sources': [],
                'authors': [],
                'rights': [],
                'places': [],
                'cities': [],
                'states': [],
                'countries': [],
                }
        pickle.dump(autolists, f)
        f.close()


def hasdir(folder):
    '''Checks if dir exists and creates.'''
    dir_check = os.path.isdir(folder)
    if not dir_check:
        os.mkdir(folder)


def debug_trace():
    '''Set a tracepoint in the Python debugger that works with Qt'''
    from PyQt4.QtCore import pyqtRemoveInputHook
    from pdb import set_trace
    pyqtRemoveInputHook()
    set_trace()

if __name__ == '__main__':
    # Criando o logger.
    hasdir('./logs')
    logger = logging.getLogger('veliger')
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    # Define formato das mensagens.
    formatter = logging.Formatter('[%(levelname)s] %(asctime)s @ %(module)s %(funcName)s (l%(lineno)d): %(message)s')
    # Cria o manipulador do console.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    # Define a formatação para o console.
    console_handler.setFormatter(formatter)
    # Adiciona o console para o logger.
    logger.addHandler(console_handler)
    # Cria o manipulador do arquivo.log.
    file_handler = logging.FileHandler('./logs/veliger.log')
    file_handler.setLevel(logging.DEBUG)
    # Define a formatação para o arquivo.log.
    file_handler.setFormatter(formatter)
    # Adiciona o arquivo.log para o logger.
    logger.addHandler(file_handler)

    # Início do programa.
    logger.info('Véliger iniciando...')

    # Roda função de inicialização.
    initialize()
    app = QApplication(sys.argv)
    app.setOrganizationName(u'CEBIMar/USP')
    app.setOrganizationDomain(u'www.usp.br/cbm')
    app.setApplicationName(u'Véliger')
    main = MainWindow()
    main.show()

    sys.exit(app.exec_())
